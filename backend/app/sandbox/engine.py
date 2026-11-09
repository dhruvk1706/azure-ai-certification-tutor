"""The simulation engine: create, configure, delete and operate simulated resources.

Every write starts with `open_sandbox`, which locks the learner's `sandbox` row and
loads all of their resources. Writes for one learner are therefore serialized, so checks
that span resources (quota, unique names, references, deletion blockers) can't be raced,
and the caller commits once at the end, so a failed operation changes nothing.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.sandbox import simulate
from app.sandbox.catalog import (
    MAX_RESOURCES_PER_LEARNER,
    TYPES,
    Conflict,
    Invalid,
    ResourceType,
    Row,
    World,
    clean_properties,
)
from app.sandbox.models import Sandbox, SandboxResource

SOFT_DELETE_RETENTION = timedelta(hours=48)


def now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _expired(row: Row, at: datetime) -> bool:
    return (
        row.state == "soft_deleted"
        and row.deleted_at is not None
        and _aware(row.deleted_at) + SOFT_DELETE_RETENTION <= at
    )


def read_world(session: Session, learner_id: int) -> World:
    """An unlocked snapshot for reads. Soft-deleted rows past retention are hidden."""
    at = now()
    rows = session.scalars(
        select(SandboxResource).where(SandboxResource.learner_id == learner_id)
    )
    return World(row for row in rows if not _expired(row, at))


def open_sandbox(session: Session, learner_id: int) -> World:
    """Lock this learner's sandbox and load their resources for a write.

    The lock is a no-op UPDATE rather than SELECT ... FOR UPDATE: both lock the row on
    PostgreSQL, but only a write takes SQLite's database lock, so this serializes on both.
    """
    # ponytail: one lock per learner serializes all of their sandbox writes. They are
    # small and quick; per-resource locks would be needed only for heavy shared use.
    lock = (
        sql_update(Sandbox)
        .where(Sandbox.learner_id == learner_id)
        .values(learner_id=Sandbox.learner_id)
    )
    if cast(CursorResult[Any], session.execute(lock)).rowcount == 0:
        try:
            with session.begin_nested():
                session.add(Sandbox(learner_id=learner_id, created_at=now()))
        except IntegrityError:
            pass  # Created concurrently: the update below waits for that commit.
        session.execute(lock)
    rows = session.scalars(
        select(SandboxResource)
        .where(SandboxResource.learner_id == learner_id)
        .execution_options(populate_existing=True)
    )
    world = World(rows)
    at = now()
    for row in [row for row in world.rows.values() if _expired(row, at)]:
        _hard_delete(session, world, row)
    return world


def _unique_key(
    rtype: ResourceType, name: str, parent: Row | None, props: dict[str, Any]
) -> str:
    if rtype.key == "role_assignment":
        return f"ra:{props['principal']}:{props['role']}:{props['scope']}"
    if rtype.namespace:
        return f"{rtype.namespace}:{name.lower()}"
    assert parent is not None
    return f"{rtype.key}:{parent.id}:{name.lower()}"


def create(
    session: Session,
    world: World,
    learner_id: int,
    type_key: str,
    parent_id: int | None,
    name: str,
    properties: dict[str, Any],
    client_request_id: str | None = None,
) -> Row:
    """Idempotent on client_request_id: a repeated request returns the same resource."""
    if client_request_id:
        for row in world.rows.values():
            if row.client_request_id == client_request_id:
                return row
    rtype = TYPES.get(type_key)
    if rtype is None:
        raise Invalid(f"Unknown resource type {type_key!r}.")
    if len(world.rows) >= MAX_RESOURCES_PER_LEARNER:
        raise Conflict(
            f"The sandbox holds at most {MAX_RESOURCES_PER_LEARNER} resources. Delete some first."
        )
    parent = world.get(parent_id) if parent_id is not None else None
    if rtype.parent is None:
        if parent_id is not None:
            raise Invalid(f"A {rtype.label.lower()} has no parent resource.")
    elif parent is None or parent.resource_type != rtype.parent:
        raise Invalid(
            f"A {rtype.label.lower()} must be created in an existing "
            f"{TYPES[rtype.parent].label.lower()}."
        )
    if rtype.auto_name:
        name = str(uuid.uuid4())
    elif not _valid_name(rtype, name):
        raise Invalid(f"{name!r} isn't a valid name. {rtype.name_help}")
    props = clean_properties(rtype, properties, world, parent)
    key = _unique_key(rtype, name, parent, props)
    clash = next((row for row in world.rows.values() if row.unique_key == key), None)
    if clash is not None:
        if clash.state == "soft_deleted":
            raise Conflict(
                f"A deleted resource named {clash.name} can still be recovered, so the "
                "name can't be reused for 48 hours. Purge it under Deleted resources "
                "to reuse the name, or recover it."
            )
        if rtype.key == "role_assignment":
            raise Conflict(
                "RoleAssignmentExists: this role is already assigned at this scope."
            )
        raise Conflict(f"A {rtype.label.lower()} named {clash.name} already exists.")
    at = now()
    row = SandboxResource(
        learner_id=learner_id,
        resource_type=rtype.key,
        name=name,
        parent_id=parent.id if parent else None,
        unique_key=key,
        properties=props,
        outputs={},
        state=rtype.initial_state,
        version=1,
        client_request_id=client_request_id,
        created_at=at,
        updated_at=at,
    )
    if rtype.key == "document_analysis":
        assert parent is not None
        row.outputs = {
            "result": simulate.analysis_result(parent.properties["pricing_tier"], props)
        }
    session.add(row)
    session.flush()
    world.add(row)
    return row


def _valid_name(rtype: ResourceType, name: str) -> bool:
    return isinstance(name, str) and bool(re.fullmatch(rtype.name_pattern, name))


def update(
    session: Session, world: World, row: Row, properties: dict[str, Any], version: int
) -> Row:
    rtype = TYPES[row.resource_type]
    if row.state == "soft_deleted":
        raise Conflict("Recover this resource before changing it.")
    if not rtype.updatable:
        raise Conflict(
            f"A {rtype.label.lower()} can't be changed. Delete it and create a new one."
        )
    if version != row.version:
        raise Conflict(
            "This resource changed since you loaded it. Reload it and apply your change again."
        )
    parent = world.get(row.parent_id) if row.parent_id else None
    props = clean_properties(rtype, properties, world, parent, row.id, row.properties)
    if props != row.properties:
        row.properties = props
        row.version += 1
        row.updated_at = now()
    return row


def _hard_delete(session: Session, world: World, row: Row) -> list[int]:
    """Delete a row and everything under it, children first."""
    removed: list[int] = []
    for child in [r for r in world.rows.values() if r.parent_id == row.id]:
        removed += _hard_delete(session, world, child)
    session.execute(sql_delete(SandboxResource).where(SandboxResource.id == row.id))
    world.remove(row.id)
    session.expunge(row)
    return [*removed, row.id]


def delete(
    session: Session, world: World, row: Row, confirm_name: str | None
) -> dict[str, list[int]]:
    """Delete like Azure: children go too, and AI accounts are soft-deleted (recoverable)."""
    if row.state == "soft_deleted":
        raise Conflict("Already deleted. Recover or purge it under Deleted resources.")
    if row.resource_type == "resource_group" and confirm_name != row.name:
        raise Invalid(
            f"Deleting a resource group deletes everything in it. Type {row.name} to confirm."
        )
    soft: list[Row] = []
    hard: list[Row] = []

    def collect(node: Row) -> None:
        if TYPES[node.resource_type].soft_delete:
            soft.append(node)  # Its children are kept with it, for recovery.
            return
        for child in world.children(node.id):
            collect(child)
        hard.append(node)

    collect(row)
    doomed = {node.id for node in hard}
    for node in hard:
        if node.resource_type != "content_filter":
            continue
        for user, _ in world.referenced_by(node.id):
            if user.id not in doomed:
                raise Conflict(
                    f"Content filter {node.name} is used by {user.name}. Assign another "
                    "filter to it first."
                )
    at = now()
    for node in soft:
        group = world.resource_group(node)
        node.outputs = {**node.outputs, "deleted_from": group.name if group else None}
        node.parent_id = None
        node.state = "soft_deleted"
        node.deleted_at = at
        node.updated_at = at
    session.flush()
    deleted: list[int] = []
    for node in hard:
        if node.id in world.rows:
            deleted += _hard_delete(session, world, node)
    return {"deleted": deleted, "soft_deleted": [node.id for node in soft]}


def purge(session: Session, world: World, row: Row) -> list[int]:
    if row.state != "soft_deleted":
        raise Conflict("Only deleted resources can be purged.")
    return _hard_delete(session, world, row)


def act(
    session: Session, world: World, row: Row, action: str, payload: dict[str, str]
) -> dict[str, Any]:
    """Run a lifecycle or test action. Returns the action's result."""
    rtype = TYPES[row.resource_type]
    if action == "recover":
        if row.state != "soft_deleted":
            raise Conflict("Only deleted resources can be recovered.")
        group_name = row.outputs.get("deleted_from")
        group = world.group_named(group_name) if group_name else None
        if group is None:
            raise Conflict(
                f"Resource group {group_name} no longer exists. Recreate it with the same "
                "name, then recover."
            )
        row.parent_id = group.id
        row.state = "succeeded"
        row.deleted_at = None
        row.outputs = {k: v for k, v in row.outputs.items() if k != "deleted_from"}
        row.version += 1
        row.updated_at = now()
        return {"ok": True}
    if row.state == "soft_deleted":
        raise Conflict("Recover this resource first.")
    if action not in rtype.actions:
        raise Invalid(f"A {rtype.label.lower()} has no action {action!r}.")
    if action in ("start", "stop"):
        wanted = "running" if action == "start" else "stopped"
        if row.state == wanted:
            raise Conflict(f"{row.name} is already {wanted}.")
        row.state = wanted
        row.updated_at = now()
        return {"ok": True, "state": wanted}
    if action == "load_sample":
        row.outputs = {**row.outputs, **simulate.load_sample(row)}
        row.version += 1
        row.updated_at = now()
        return {"ok": True, **row.outputs}
    if action == "test_prompt":
        return simulate.prompt_test(world, row, payload.get("prompt_id", ""))
    if action == "test":
        result = simulate.agent_test(world, row, payload.get("question_id", ""))
    else:
        result = simulate.connection_test(world, row)
    # Test results aren't configuration: the version stays, so labs can tell whether the
    # test ran on the current configuration.
    row.outputs = {
        **row.outputs,
        "last_test": {
            **result,
            "fingerprint": simulate.fingerprint(world),
            "at": now().isoformat(),
        },
    }
    return result
