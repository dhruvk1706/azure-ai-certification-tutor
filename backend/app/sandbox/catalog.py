"""Simulated Azure resource types: fields, naming rules and validation.

A teaching model, not Azure. Each type follows the Microsoft Learn page in its
`docs_url`, simplified where the `note` says so. Validation here plays the part of
Azure Resource Manager: it rejects what Azure would reject when you save (bad names,
values outside limits, references to resources that don't exist). Mistakes Azure would
accept, such as a wrong region for a scenario, are saved, and labs grade them.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.sandbox.models import SandboxResource

Row = SandboxResource


class Invalid(ValueError):
    """The request is malformed for this resource type (HTTP 422)."""


class Conflict(ValueError):
    """The request clashes with other resources or limits (HTTP 409)."""


# --- Reference data (simplified, see each comment) ---

# Region name: (display name, data zone). Data zones per the Foundry deployment types
# page. Only a few regions are simulated, and every model is treated as available in
# every simulated region, which real Azure doesn't promise.
REGIONS: dict[str, tuple[str, str | None]] = {
    "eastus": ("East US", "US"),
    "eastus2": ("East US 2", "US"),
    "westus3": ("West US 3", "US"),
    "southcentralus": ("South Central US", "US"),
    "swedencentral": ("Sweden Central", "EU"),
    "westeurope": ("West Europe", "EU"),
    "northeurope": ("North Europe", "EU"),
    "francecentral": ("France Central", "EU"),
    "germanywestcentral": ("Germany West Central", "EU"),
    "uksouth": ("UK South", None),
    "switzerlandnorth": ("Switzerland North", None),
    "canadaeast": ("Canada East", None),
}


@dataclass(frozen=True)
class Model:
    kind: str  # "chat" or "embedding"
    versions: tuple[str, ...]
    deployment_types: tuple[str, ...]
    max_dimensions: int | None = None
    fixed_dimensions: bool = False


STANDARD_TYPES = ("GlobalStandard", "DataZoneStandard", "Standard")
PROVISIONED_TYPES = (
    "GlobalProvisionedManaged",
    "DataZoneProvisionedManaged",
    "ProvisionedManaged",
)
BATCH_TYPES = ("GlobalBatch", "DataZoneBatch")
DEPLOYMENT_TYPES = STANDARD_TYPES + PROVISIONED_TYPES + BATCH_TYPES
DEPLOYMENT_TYPE_LABELS = (
    "Global Standard",
    "Data Zone Standard",
    "Standard (regional)",
    "Global Provisioned",
    "Data Zone Provisioned",
    "Regional Provisioned",
    "Global Batch",
    "Data Zone Batch",
)
_CHAT_TYPES = DEPLOYMENT_TYPES
_EMBEDDING_TYPES = ("GlobalStandard", "Standard")

# A small simulated model catalog. Versions are real version strings; availability
# per deployment type is simplified.
MODELS: dict[str, Model] = {
    "gpt-4.1": Model("chat", ("2025-04-14",), _CHAT_TYPES),
    "gpt-4.1-mini": Model("chat", ("2025-04-14",), _CHAT_TYPES),
    "gpt-4o": Model("chat", ("2024-11-20", "2024-08-06"), _CHAT_TYPES),
    "gpt-4o-mini": Model("chat", ("2024-07-18",), _CHAT_TYPES),
    "text-embedding-3-small": Model("embedding", ("1",), _EMBEDDING_TYPES, 1536),
    "text-embedding-3-large": Model("embedding", ("1",), _EMBEDDING_TYPES, 3072),
    "text-embedding-ada-002": Model(
        "embedding", ("2",), _EMBEDDING_TYPES, 1536, fixed_dimensions=True
    ),
}
# ponytail: one flat simulated quota per model, deployment type and region. Real quota
# differs per model, subscription and region; raise these if labs need more headroom.
STANDARD_QUOTA_K_TPM = 300
PROVISIONED_QUOTA_PTU = 100
MIN_PTU = 15

UPGRADE_OPTIONS = (
    "OnceNewDefaultVersionAvailable",
    "OnceCurrentVersionExpired",
    "NoAutoUpgrade",
)
THRESHOLDS = ("Low", "Medium", "High")
THRESHOLD_LABELS = (
    "Low: blocks low, medium and high severity",
    "Medium: blocks medium and high severity",
    "High: blocks only high severity",
)
HARM_CATEGORIES = (
    ("hate", "Hate and fairness"),
    ("sexual", "Sexual"),
    ("violence", "Violence"),
    ("self_harm", "Self-harm"),
)
DIRECTIONS = (("prompt", "prompts"), ("completion", "completions"))

SEARCH_TIERS = (
    "free",
    "basic",
    "standard",
    "standard2",
    "standard3",
    "storage_optimized_l1",
    "storage_optimized_l2",
)
SEARCH_TIER_LABELS = (
    "Free",
    "Basic",
    "Standard S1",
    "Standard S2",
    "Standard S3",
    "Storage Optimized L1",
    "Storage Optimized L2",
)
# Tier: (max replicas, max partitions, max indexes), from the service limits page.
SEARCH_LIMITS: dict[str, tuple[int, int, int]] = {
    "free": (1, 1, 3),
    "basic": (3, 3, 15),
    "standard": (12, 12, 50),
    "standard2": (12, 12, 200),
    "standard3": (12, 12, 200),
    "storage_optimized_l1": (12, 12, 10),
    "storage_optimized_l2": (12, 12, 10),
}
MAX_SEARCH_UNITS = 36
PARTITION_COUNTS = (1, 2, 3, 4, 6, 12)
FIELD_TYPES = (
    "Edm.String",
    "Edm.Int32",
    "Edm.Int64",
    "Edm.Double",
    "Edm.Boolean",
    "Edm.DateTimeOffset",
    "Collection(Edm.String)",
    "Collection(Edm.Single)",
)
VECTOR_TYPE = "Collection(Edm.Single)"
QUERY_TYPES = (
    "simple",
    "semantic",
    "vector",
    "vector_simple_hybrid",
    "vector_semantic_hybrid",
)
QUERY_TYPE_LABELS = (
    "Simple (keyword)",
    "Semantic",
    "Vector",
    "Hybrid (vector + keyword)",
    "Hybrid + semantic",
)
ROLES = (
    "Cognitive Services OpenAI User",
    "Cognitive Services OpenAI Contributor",
    "Cognitive Services User",
    "Azure AI User",
    "Search Index Data Reader",
    "Search Index Data Contributor",
    "Search Service Contributor",
    "Reader",
    "Contributor",
    "Owner",
)
# Roles whose data actions allow model inference with Microsoft Entra ID. Contributor and
# Owner manage resources but can't call the model with a token (RBAC page).
INFERENCE_ROLES = frozenset(ROLES[:4])

SAMPLE_DOCUMENTS = (
    "contoso-invoice-1042.pdf",
    "coffee-receipt.jpg",
    "employee-handbook.pdf",
    "scanned-letter.png",
)
DOCUMENT_MODELS = (
    "prebuilt-read",
    "prebuilt-layout",
    "prebuilt-invoice",
    "prebuilt-receipt",
    "prebuilt-idDocument",
    "prebuilt-contract",
)


def region_label(region: str) -> str:
    return REGIONS.get(region, (region, None))[0]


def data_zone(region: str) -> str | None:
    return REGIONS.get(region, ("", None))[1]


# --- Fields ---


@dataclass(frozen=True)
class F:
    key: str
    label: str
    kind: str  # text, textarea, select, number, bool, ref, strings, list
    options: tuple[Any, ...] = ()
    labels: tuple[str, ...] = ()
    default: Any = None
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    integer: bool = True
    max_length: int = 120
    pattern: str | None = None
    help: str = ""
    refs: tuple[str, ...] = ()
    updatable: bool = True
    items: tuple["F", ...] = ()
    max_items: int = 20

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "options": list(self.options),
            "labels": list(self.labels),
            "default": self.default,
            "required": self.required,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "integer": self.integer,
            "max_length": self.max_length,
            "help": self.help,
            "refs": list(self.refs),
            "updatable": self.updatable,
            "items": [item.describe() for item in self.items],
            "max_items": self.max_items,
        }


def _region(updatable: bool = False) -> F:
    return F(
        "region",
        "Region",
        "select",
        tuple(REGIONS),
        tuple(label for label, _ in REGIONS.values()),
        default="eastus",
        updatable=updatable,
        help="Where the resource runs. It can't be changed after creation.",
    )


_PUBLIC_ACCESS = F(
    "public_network_access",
    "Public network access",
    "select",
    ("Enabled", "Disabled"),
    default="Enabled",
    help="Disabled means only private endpoints can reach the resource.",
)
_DISABLE_LOCAL_AUTH = F(
    "disable_local_auth",
    "Disable key-based authentication",
    "bool",
    default=False,
    help="When on, callers must use Microsoft Entra ID (keyless) instead of keys.",
)


@dataclass(frozen=True)
class RuleContext:
    world: "World"
    parent: Row | None
    self_id: int | None
    old: dict[str, Any] | None


Rule = Callable[[dict[str, Any], RuleContext], None]


@dataclass(frozen=True)
class ResourceType:
    key: str
    label: str
    arm_type: str
    parent: str | None
    description: str
    docs_url: str
    fields: tuple[F, ...]
    name_pattern: str = r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}[A-Za-z0-9]$"
    name_help: str = (
        "2-64 letters, digits and hyphens, starting and ending with a letter or digit."
    )
    # Names are unique per learner in this namespace, otherwise per parent.
    namespace: str | None = None
    soft_delete: bool = False
    auto_name: bool = False
    updatable: bool = True
    actions: tuple[str, ...] = ()
    initial_state: str = "succeeded"
    note: str = ""
    rules: tuple[Rule, ...] = ()

    def field(self, key: str) -> F:
        return next(f for f in self.fields if f.key == key)

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "arm_type": self.arm_type,
            "parent": self.parent,
            "description": self.description,
            "docs_url": self.docs_url,
            "fields": [f.describe() for f in self.fields],
            "name_help": self.name_help,
            "soft_delete": self.soft_delete,
            "auto_name": self.auto_name,
            "updatable": self.updatable,
            "actions": list(self.actions),
            "note": self.note,
        }


# --- The world: one learner's resources ---


class World:
    """All of one learner's resources, loaded while their sandbox is locked."""

    def __init__(self, rows: Iterable[Row]) -> None:
        self.rows: dict[int, Row] = {row.id: row for row in rows}

    def add(self, row: Row) -> None:
        self.rows[row.id] = row

    def remove(self, row_id: int) -> None:
        self.rows.pop(row_id, None)

    def get(self, row_id: Any) -> Row | None:
        """An active resource, never a soft-deleted one."""
        row = self.rows.get(row_id) if isinstance(row_id, int) else None
        return row if row and row.state != "soft_deleted" else None

    def children(self, row_id: int, resource_type: str | None = None) -> list[Row]:
        return sorted(
            (
                row
                for row in self.rows.values()
                if row.parent_id == row_id
                and row.state != "soft_deleted"
                and resource_type in (None, row.resource_type)
            ),
            key=lambda row: row.id,
        )

    def descendants(self, row_id: int) -> list[Row]:
        found: list[Row] = []
        for child in (row for row in self.rows.values() if row.parent_id == row_id):
            found.append(child)
            found.extend(self.descendants(child.id))
        return found

    def of_type(self, resource_type: str) -> list[Row]:
        return sorted(
            (
                row
                for row in self.rows.values()
                if row.resource_type == resource_type and row.state != "soft_deleted"
            ),
            key=lambda row: row.id,
        )

    def resource_group(self, row: Row) -> Row | None:
        current: Row | None = row
        while current and current.resource_type != "resource_group":
            current = self.rows.get(current.parent_id) if current.parent_id else None
        return current

    def group_named(self, name: str) -> Row | None:
        return next(
            (
                row
                for row in self.of_type("resource_group")
                if row.name.lower() == name.lower()
            ),
            None,
        )

    def region_of(self, row: Row) -> str:
        current: Row | None = row
        while current:
            if "region" in current.properties:
                return str(current.properties["region"])
            current = self.rows.get(current.parent_id) if current.parent_id else None
        return ""

    def referenced_by(self, row_id: int) -> list[tuple[Row, str]]:
        """Active resources whose properties point at this one, with the field."""
        found = []
        for row in self.rows.values():
            if row.state == "soft_deleted" or row.id == row_id:
                continue
            for spec in TYPES[row.resource_type].fields:
                if spec.kind == "ref" and row.properties.get(spec.key) == row_id:
                    found.append((row, spec.label))
        return found


# --- Rules ---


def _model(props: dict[str, Any]) -> Model:
    return MODELS[props["model"]]


def _deployment_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    model = _model(props)
    if props["model_version"] not in model.versions:
        raise Invalid(
            f"{props['model']} has no version {props['model_version']} in this "
            f"catalog. Available: {', '.join(model.versions)}."
        )
    kind = props["deployment_type"]
    if kind not in model.deployment_types:
        raise Invalid(
            f"{props['model']} can't be deployed as {kind} in the simulated catalog."
        )
    assert ctx.parent is not None
    region = ctx.world.region_of(ctx.parent)
    if kind.startswith("DataZone") and data_zone(region) is None:
        raise Invalid(
            f"{kind} needs a resource in a region that belongs to a data zone. "
            f"{region_label(region)} isn't in one (this sandbox simulates the US and EU "
            "data zones)."
        )
    capacity = props["capacity"]
    provisioned = kind in PROVISIONED_TYPES
    if provisioned and (capacity < MIN_PTU or capacity % 5):
        raise Invalid(
            f"Provisioned capacity is in PTUs: at least {MIN_PTU}, in steps of 5 "
            "(simulated minimum)."
        )
    used = sum(
        other.properties["capacity"]
        for other in ctx.world.of_type("model_deployment")
        if other.id != ctx.self_id
        and other.properties["model"] == props["model"]
        and other.properties["deployment_type"] == kind
        and ctx.world.region_of(other) == region
        and ctx.world.get(other.parent_id) is not None
    )
    limit = PROVISIONED_QUOTA_PTU if provisioned else STANDARD_QUOTA_K_TPM
    unit = "PTU" if provisioned else "K tokens per minute"
    if used + capacity > limit:
        raise Conflict(
            f"InsufficientQuota: {props['model']} {kind} in {region_label(region)} "
            f"has {limit - used} of {limit} {unit} left (simulated quota), and this "
            f"asks for {capacity}. Lower the capacity or free quota elsewhere."
        )
    filter_id = props.get("content_filter")
    if filter_id is not None:
        content_filter = ctx.world.get(filter_id)
        if content_filter is None or content_filter.parent_id != ctx.parent.id:
            raise Invalid(
                "A deployment can only use a content filter of its own Foundry resource."
            )


def _filter_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    if any(len(term) > 100 for term in props["blocklist_terms"]):
        raise Invalid("Blocklist terms can be at most 100 characters.")


def _search_service_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    tier = props["tier"]
    max_replicas, max_partitions, _ = SEARCH_LIMITS[tier]
    replicas, partitions = props["replicas"], props["partitions"]
    if partitions not in PARTITION_COUNTS:
        raise Invalid(
            f"Partitions must be one of {', '.join(map(str, PARTITION_COUNTS))}."
        )
    if replicas > max_replicas or partitions > max_partitions:
        raise Invalid(
            f"The {tier} tier allows at most {max_replicas} replicas and "
            f"{max_partitions} partitions."
        )
    if tier not in ("free", "basic") and replicas * partitions > MAX_SEARCH_UNITS:
        raise Invalid(
            f"Replicas Ã— partitions can be at most {MAX_SEARCH_UNITS} search units."
        )
    if tier == "free" and any(
        other.properties["tier"] == "free" and other.id != ctx.self_id
        for other in ctx.world.of_type("search_service")
    ):
        raise Conflict("A subscription can have only one free search service.")


def _index_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    fields = props["fields"]
    names = [f["name"].lower() for f in fields]
    if len(set(names)) != len(names):
        raise Invalid("Field names must be unique.")
    keys = [f for f in fields if f["key"]]
    if len(keys) != 1:
        raise Invalid("An index needs exactly one key field.")
    if keys[0]["type"] != "Edm.String":
        raise Invalid("The key field must be of type Edm.String.")
    for f in fields:
        name = f["name"]
        if f["type"] == VECTOR_TYPE:
            if f.get("dimensions") is None:
                raise Invalid(f"Vector field {name} needs dimensions (2-4096).")
            if not f["searchable"]:
                raise Invalid(f"Vector field {name} must be searchable.")
            if f["filterable"] or f["sortable"] or f["facetable"] or f["key"]:
                raise Invalid(
                    f"Vector field {name} can't be key, filterable, sortable or facetable."
                )
        else:
            if f.get("dimensions") is not None:
                raise Invalid(f"Only vector fields take dimensions ({name}).")
            if f["searchable"] and "String" not in f["type"]:
                raise Invalid(f"Only string fields can be searchable ({name}).")
            if f["type"].startswith("Collection") and f["sortable"]:
                raise Invalid(f"Collection fields can't be sortable ({name}).")
    by_name = {f["name"]: f for f in fields}
    semantic = [
        props.get("semantic_title_field") or None,
        *props["semantic_content_fields"],
    ]
    for name in filter(None, semantic):
        target = by_name.get(name)
        if not target or target["type"] != "Edm.String" or not target["searchable"]:
            raise Invalid(
                f"Semantic configuration field {name} must be a searchable Edm.String "
                "field of this index."
            )
    vectorizer = props.get("vectorizer")
    if vectorizer is not None:
        deployment = ctx.world.get(vectorizer)
        assert deployment is not None
        if _model(deployment.properties).kind != "embedding":
            raise Invalid(
                f"Vectorizer {deployment.name} deploys {deployment.properties['model']}, "
                "which isn't an embedding model."
            )
    if ctx.old is not None:
        old_fields = {f["name"]: f for f in ctx.old["fields"]}
        for name, old in old_fields.items():
            new = by_name.get(name)
            if not new or any(
                new.get(attribute) != old.get(attribute)
                for attribute in (
                    "type",
                    "key",
                    "dimensions",
                    "searchable",
                    "filterable",
                    "sortable",
                    "facetable",
                )
            ):
                raise Conflict(
                    f"Existing field {name} can't be changed or removed. Azure AI Search "
                    "only lets you add fields; create a new index and reload it instead."
                )
    else:
        assert ctx.parent is not None
        limit = SEARCH_LIMITS[ctx.parent.properties["tier"]][2]
        if len(ctx.world.children(ctx.parent.id, "search_index")) >= limit:
            raise Conflict(f"This tier allows at most {limit} indexes per service.")


def _agent_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    assert ctx.parent is not None
    deployment = ctx.world.get(props["model_deployment"])
    assert deployment is not None
    if deployment.parent_id != ctx.parent.parent_id:
        raise Invalid(
            "The agent's model must be deployed on the Foundry resource that holds "
            "this project."
        )
    if _model(deployment.properties).kind != "chat":
        raise Invalid(
            f"{deployment.name} deploys an embedding model. Agents need a chat model."
        )
    if not props["search_tool"]:
        return
    connection = ctx.world.get(props.get("search_connection"))
    index = ctx.world.get(props.get("search_index"))
    if connection is None or index is None:
        raise Invalid("The Azure AI Search tool needs a connection and an index.")
    if connection.parent_id != ctx.parent.id:
        raise Invalid("Use a connection that belongs to this project.")
    if index.parent_id != connection.properties["target"]:
        raise Invalid(
            f"Index {index.name} isn't on the search service that connection "
            f"{connection.name} points to."
        )


def _free_document_intelligence(props: dict[str, Any], ctx: RuleContext) -> None:
    if props["pricing_tier"] == "F0" and any(
        other.properties["pricing_tier"] == "F0" and other.id != ctx.self_id
        for other in ctx.world.of_type("document_intelligence")
    ):
        raise Conflict(
            "A subscription can have only one free (F0) Document Intelligence resource."
        )


def _analysis_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    if props["output_format"] == "markdown" and props["model_id"] != "prebuilt-layout":
        raise Invalid("The sandbox simulates markdown output for prebuilt-layout only.")


def _role_rules(props: dict[str, Any], ctx: RuleContext) -> None:
    app = ctx.world.get(props["principal"])
    assert app is not None
    if app.properties["identity"] != "SystemAssigned":
        raise Invalid(
            f"PrincipalNotFound: {app.name} has no managed identity. Turn on its "
            "system-assigned identity first."
        )


# --- Types ---

_COG_NOTE = (
    "Names are unique within your sandbox only; in Azure the custom subdomain must be "
    "globally unique. Deleted resources stay recoverable for 48 hours, as in Azure."
)
_DOCS = "https://learn.microsoft.com/en-us/azure/"

_TYPES = (
    ResourceType(
        key="resource_group",
        label="Resource group",
        arm_type="Microsoft.Resources/resourceGroups",
        parent=None,
        description="A container that holds related resources for a solution.",
        docs_url=_DOCS
        + "azure-resource-manager/management/manage-resource-groups-portal",
        fields=(_region(),),
        name_pattern=r"^[-\w.()]{0,89}[-\w()]$",
        name_help="1-90 letters, digits, underscores, hyphens, periods and parentheses; can't end with a period.",
        namespace="rg",
    ),
    ResourceType(
        key="foundry_resource",
        label="Foundry resource",
        arm_type="Microsoft.CognitiveServices/accounts (kind AIServices)",
        parent="resource_group",
        description="The Azure resource behind Foundry: holds model deployments, projects, guardrails and the endpoint apps call.",
        docs_url=_DOCS + "ai-foundry/how-to/create-resource-template",
        fields=(
            _region(),
            F("pricing_tier", "Pricing tier", "select", ("S0",), default="S0"),
            _PUBLIC_ACCESS,
            _DISABLE_LOCAL_AUTH,
            F(
                "identity",
                "Managed identity",
                "select",
                ("None", "SystemAssigned"),
                default="None",
            ),
        ),
        namespace="cog",
        soft_delete=True,
        note=_COG_NOTE,
    ),
    ResourceType(
        key="foundry_project",
        label="Foundry project",
        arm_type="Microsoft.CognitiveServices/accounts/projects",
        parent="foundry_resource",
        description="A workspace inside a Foundry resource for building agents and apps, with its own connections.",
        docs_url=_DOCS + "ai-foundry/how-to/create-projects",
        fields=(
            F("display_name", "Display name", "text", required=False, default=""),
            F(
                "description",
                "Description",
                "textarea",
                required=False,
                default="",
                max_length=500,
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$",
        name_help="2-64 letters, digits, hyphens and underscores, starting with a letter or digit.",
    ),
    ResourceType(
        key="model_deployment",
        label="Model deployment",
        arm_type="Microsoft.CognitiveServices/accounts/deployments",
        parent="foundry_resource",
        description="A deployed model with a name apps call, a deployment type that decides where data is processed, and capacity.",
        docs_url=_DOCS + "ai-foundry/foundry-models/concepts/deployment-types",
        fields=(
            F(
                "model",
                "Model",
                "select",
                tuple(MODELS),
                default="gpt-4o-mini",
                updatable=False,
            ),
            F(
                "model_version",
                "Model version",
                "text",
                default="2024-07-18",
                help="One of the model's versions.",
            ),
            F(
                "deployment_type",
                "Deployment type",
                "select",
                DEPLOYMENT_TYPES,
                DEPLOYMENT_TYPE_LABELS,
                default="GlobalStandard",
                updatable=False,
                help="Global may process data in any region, Data Zone only within the data zone, Standard only in the resource's region.",
            ),
            F(
                "capacity",
                "Capacity",
                "number",
                default=10,
                minimum=1,
                maximum=1000,
                help="Thousands of tokens per minute for Standard and Batch types; PTUs for provisioned types.",
            ),
            F(
                "version_upgrade_option",
                "Version upgrade policy",
                "select",
                UPGRADE_OPTIONS,
                (
                    "Upgrade once a new default version is available",
                    "Upgrade when the current version expires",
                    "No automatic upgrade",
                ),
                default="OnceNewDefaultVersionAvailable",
            ),
            F(
                "content_filter",
                "Content filter",
                "ref",
                refs=("content_filter",),
                required=False,
                help="Leave empty to use the default policy (DefaultV2).",
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$",
        name_help="2-64 letters, digits, periods, hyphens and underscores.",
        actions=("test_prompt",),
        note="Quota is a flat simulated limit per model, deployment type and region. Model availability per region isn't simulated.",
        rules=(_deployment_rules,),
    ),
    ResourceType(
        key="content_filter",
        label="Content filter (guardrail)",
        arm_type="Microsoft.CognitiveServices/accounts/raiPolicies",
        parent="foundry_resource",
        description="Severity thresholds for harm categories, Prompt Shields and blocklists, applied to the deployments that use it.",
        docs_url=_DOCS + "ai-foundry/openai/concepts/content-filter",
        fields=tuple(
            F(
                f"{category}_{direction}",
                f"{label}: {noun}",
                "select",
                THRESHOLDS,
                THRESHOLD_LABELS,
                default="Medium",
            )
            for category, label in HARM_CATEGORIES
            for direction, noun in DIRECTIONS
        )
        + (
            F(
                "jailbreak_shield",
                "Prompt Shields: user prompt attacks (jailbreak)",
                "bool",
                default=True,
            ),
            F(
                "indirect_attack_shield",
                "Prompt Shields: indirect attacks in documents",
                "bool",
                default=False,
            ),
            F(
                "protected_material_text",
                "Protected material for text",
                "bool",
                default=True,
            ),
            F(
                "protected_material_code",
                "Protected material for code",
                "bool",
                default=True,
            ),
            F(
                "blocklist_terms",
                "Custom blocklist terms",
                "strings",
                default=[],
                required=False,
                max_items=20,
                help="One term per line. Prompts containing a term are blocked.",
            ),
        ),
        name_pattern=r"^(?!(?i:defaultv2|microsoft\.default)$)[A-Za-z0-9][A-Za-z0-9_-]{1,63}$",
        name_help="2-64 letters, digits, hyphens and underscores. DefaultV2 is reserved.",
        note="Turning a category off, or annotate-only mode, needs Microsoft's approval in Azure and isn't simulated. Completion filtering is configured but test prompts only exercise the prompt side.",
        rules=(_filter_rules,),
    ),
    ResourceType(
        key="search_service",
        label="Azure AI Search service",
        arm_type="Microsoft.Search/searchServices",
        parent="resource_group",
        description="Hosts search indexes used for keyword, vector, hybrid and semantic retrieval.",
        docs_url=_DOCS + "search/search-sku-tier",
        fields=(
            _region(),
            F(
                "tier",
                "Pricing tier",
                "select",
                SEARCH_TIERS,
                SEARCH_TIER_LABELS,
                default="basic",
                updatable=False,
            ),
            F(
                "replicas",
                "Replicas",
                "number",
                default=1,
                minimum=1,
                maximum=12,
                help="Two replicas give a query SLA, three a query and indexing SLA.",
            ),
            F("partitions", "Partitions", "number", default=1, minimum=1, maximum=12),
            F(
                "semantic_ranker",
                "Semantic ranker",
                "select",
                ("disabled", "free", "standard"),
                ("Disabled", "Free plan", "Standard plan"),
                default="disabled",
            ),
            _DISABLE_LOCAL_AUTH,
            _PUBLIC_ACCESS,
        ),
        name_pattern=r"^(?!-)(?!.-)(?!.*--)[a-z0-9-]{1,59}[a-z0-9]$",
        name_help="2-60 lowercase letters, digits and dashes; no dash in the first two characters or at the end, no consecutive dashes.",
        namespace="search",
        note="Names are unique within your sandbox only (Azure requires global uniqueness). The tier can't be changed here after creation.",
        rules=(_search_service_rules,),
    ),
    ResourceType(
        key="search_index",
        label="Search index",
        arm_type="Microsoft.Search/searchServices/indexes",
        parent="search_service",
        description="A schema of fields with attributes, plus optional vector search and semantic configuration.",
        docs_url=_DOCS + "search/vector-search-how-to-create-index",
        fields=(
            F(
                "fields",
                "Fields",
                "list",
                default=[],
                max_items=30,
                items=(
                    F(
                        "name",
                        "Name",
                        "text",
                        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$",
                        max_length=128,
                    ),
                    F("type", "Type", "select", FIELD_TYPES, default="Edm.String"),
                    F("key", "Key", "bool", default=False),
                    F("searchable", "Searchable", "bool", default=True),
                    F("filterable", "Filterable", "bool", default=False),
                    F("sortable", "Sortable", "bool", default=False),
                    F("facetable", "Facetable", "bool", default=False),
                    F("retrievable", "Retrievable", "bool", default=True),
                    F(
                        "dimensions",
                        "Dimensions",
                        "number",
                        required=False,
                        minimum=2,
                        maximum=4096,
                    ),
                ),
            ),
            F(
                "vector_algorithm",
                "Vector algorithm",
                "select",
                ("hnsw", "exhaustiveKnn"),
                ("HNSW (approximate)", "Exhaustive KNN"),
                default="hnsw",
            ),
            F(
                "vectorizer",
                "Vectorizer (embedding deployment)",
                "ref",
                refs=("model_deployment",),
                required=False,
                help="Lets the service turn query text into vectors with this embedding model.",
            ),
            F(
                "semantic_title_field",
                "Semantic configuration: title field",
                "text",
                required=False,
                default="",
            ),
            F(
                "semantic_content_fields",
                "Semantic configuration: content fields",
                "strings",
                required=False,
                default=[],
                max_items=10,
            ),
        ),
        name_pattern=r"^(?!.*--)[a-z0-9][a-z0-9-]{0,127}$",
        name_help="Up to 128 lowercase letters, digits and dashes, starting with a letter or digit.",
        actions=("load_sample",),
        note="One vector profile per index. Documents come from a built-in sample set, not your data.",
        rules=(_index_rules,),
    ),
    ResourceType(
        key="foundry_connection",
        label="Project connection",
        arm_type="Microsoft.CognitiveServices/accounts/projects/connections",
        parent="foundry_project",
        description="Lets a project's agents and tools use another resource, such as Azure AI Search.",
        docs_url=_DOCS + "ai-foundry/how-to/connections-add",
        fields=(
            F("target", "Azure AI Search service", "ref", refs=("search_service",)),
            F(
                "auth_type",
                "Authentication",
                "select",
                ("EntraId", "ApiKey"),
                ("Microsoft Entra ID (keyless)", "API key"),
                default="ApiKey",
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$",
        name_help="2-64 letters, digits, hyphens and underscores.",
        note="With Entra ID, the sandbox assumes the project's identity holds the Search Index Data Reader role.",
    ),
    ResourceType(
        key="agent",
        label="Agent",
        arm_type="Foundry Agent Service agent (data plane)",
        parent="foundry_project",
        description="An agent with instructions, a chat model and, optionally, an Azure AI Search tool for grounded answers.",
        docs_url=_DOCS + "ai-foundry/agents/how-to/tools/azure-ai-search",
        fields=(
            F(
                "model_deployment",
                "Model deployment",
                "ref",
                refs=("model_deployment",),
            ),
            F(
                "instructions",
                "Instructions",
                "textarea",
                default="",
                required=False,
                max_length=4000,
            ),
            F(
                "temperature",
                "Temperature",
                "number",
                default=1.0,
                minimum=0,
                maximum=2,
                integer=False,
            ),
            F("search_tool", "Azure AI Search tool", "bool", default=False),
            F(
                "search_connection",
                "Search connection",
                "ref",
                refs=("foundry_connection",),
                required=False,
            ),
            F(
                "search_index",
                "Search index",
                "ref",
                refs=("search_index",),
                required=False,
            ),
            F(
                "query_type",
                "Query type",
                "select",
                QUERY_TYPES,
                QUERY_TYPE_LABELS,
                default="vector_simple_hybrid",
            ),
            F(
                "top_k",
                "Documents to retrieve (top k)",
                "number",
                default=5,
                minimum=1,
                maximum=50,
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$",
        name_help="1-63 letters, digits, hyphens and underscores.",
        actions=("test",),
        note="Test runs are simulated by rules: no model is called and answers come from a built-in sample corpus.",
        rules=(_agent_rules,),
    ),
    ResourceType(
        key="document_intelligence",
        label="Document Intelligence",
        arm_type="Microsoft.CognitiveServices/accounts (kind FormRecognizer)",
        parent="resource_group",
        description="Analyzes documents with OCR, layout and prebuilt or custom extraction models.",
        docs_url=_DOCS + "ai-services/document-intelligence/model-overview",
        fields=(
            _region(),
            F(
                "pricing_tier",
                "Pricing tier",
                "select",
                ("F0", "S0"),
                ("Free F0", "Standard S0"),
                default="F0",
            ),
            _DISABLE_LOCAL_AUTH,
            _PUBLIC_ACCESS,
        ),
        namespace="cog",
        soft_delete=True,
        note=_COG_NOTE
        + " The free tier analyzes only the first two pages of a document.",
        rules=(_free_document_intelligence,),
    ),
    ResourceType(
        key="document_analysis",
        label="Document analysis run",
        arm_type="Document Intelligence analyze operation (data plane)",
        parent="document_intelligence",
        description="Runs one model on one sample document. The result is stored with the run.",
        docs_url=_DOCS + "ai-services/document-intelligence/prebuilt/layout",
        fields=(
            F("document", "Sample document", "select", SAMPLE_DOCUMENTS),
            F("model_id", "Model", "select", DOCUMENT_MODELS, default="prebuilt-read"),
            F(
                "output_format",
                "Output content format",
                "select",
                ("text", "markdown"),
                default="text",
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$",
        name_help="1-63 letters, digits, hyphens and underscores.",
        updatable=False,
        note="Results are precomputed for four sample documents; no real analysis runs.",
        rules=(_analysis_rules,),
    ),
    ResourceType(
        key="web_app",
        label="Web app",
        arm_type="Microsoft.Web/sites",
        parent="resource_group",
        description="An App Service app that calls your AI resources, with an optional managed identity.",
        docs_url=_DOCS + "app-service/overview-managed-identity",
        fields=(
            _region(),
            F(
                "runtime",
                "Runtime stack",
                "select",
                ("python-3.12", "node-22", "dotnet-8"),
                default="python-3.12",
            ),
            F(
                "identity",
                "System-assigned managed identity",
                "select",
                ("None", "SystemAssigned"),
                default="None",
            ),
            F(
                "target",
                "AI endpoint the app calls",
                "ref",
                refs=("foundry_resource",),
                required=False,
            ),
            F(
                "auth_mode",
                "How the app authenticates",
                "select",
                ("ApiKey", "ManagedIdentity"),
                ("API key in app settings", "Managed identity (keyless)"),
                default="ApiKey",
            ),
            F(
                "vnet_integration",
                "Virtual network integration",
                "text",
                required=False,
                default="",
                help="Name of the virtual network the app's outbound traffic uses.",
            ),
        ),
        namespace="web",
        initial_state="running",
        actions=("start", "stop", "test_connection"),
        note="Virtual networks are names only: an app reaches a private endpoint when both name the same network.",
    ),
    ResourceType(
        key="role_assignment",
        label="Role assignment",
        arm_type="Microsoft.Authorization/roleAssignments",
        parent="resource_group",
        description="Grants a role to a managed identity at a scope. Can't be edited, only removed and recreated.",
        docs_url=_DOCS + "ai-services/openai/how-to/role-based-access-control",
        fields=(
            F("principal", "Assign to (web app identity)", "ref", refs=("web_app",)),
            F("role", "Role", "select", ROLES, default="Reader"),
            F(
                "scope",
                "Scope",
                "ref",
                refs=(
                    "foundry_resource",
                    "search_service",
                    "document_intelligence",
                    "resource_group",
                ),
            ),
        ),
        auto_name=True,
        updatable=False,
        note="Only web app identities can be principals in the sandbox. Role permissions are simplified to whether a role allows inference with Entra ID.",
        rules=(_role_rules,),
    ),
    ResourceType(
        key="private_endpoint",
        label="Private endpoint",
        arm_type="Microsoft.Network/privateEndpoints",
        parent="resource_group",
        description="A private IP address in a virtual network for a resource, so it can be reached with public access disabled.",
        docs_url=_DOCS + "ai-services/cognitive-services-virtual-networks",
        fields=(
            _region(),
            F(
                "target",
                "Resource",
                "ref",
                refs=("foundry_resource", "search_service", "document_intelligence"),
            ),
            F(
                "virtual_network",
                "Virtual network",
                "text",
                max_length=64,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$",
            ),
            F(
                "subnet",
                "Subnet",
                "text",
                default="default",
                max_length=80,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$",
            ),
        ),
        name_pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}[A-Za-z0-9_]$",
        name_help="2-80 letters, digits, underscores, periods and hyphens.",
        updatable=False,
        note="DNS zones and network security aren't simulated.",
    ),
)
TYPES: dict[str, ResourceType] = {t.key: t for t in _TYPES}
MAX_RESOURCES_PER_LEARNER = 200


# --- Property validation ---


def _clean_value(spec: F, value: Any, where: str) -> Any:
    label = f"{where}{spec.label}"
    if value is None or (value == "" and spec.kind in ("ref", "number")):
        if spec.required and spec.default is None:
            raise Invalid(f"{label} is required.")
        return list(spec.default) if isinstance(spec.default, list) else spec.default
    if spec.kind in ("text", "textarea"):
        if not isinstance(value, str):
            raise Invalid(f"{label} must be text.")
        value = value.replace("\x00", "").strip()
        if len(value) > spec.max_length:
            raise Invalid(f"{label} can be at most {spec.max_length} characters.")
        if spec.required and not value:
            raise Invalid(f"{label} is required.")
        if value and spec.pattern and not re.fullmatch(spec.pattern, value):
            raise Invalid(f"{label} {value!r} isn't a valid name.")
        return value
    if spec.kind == "select":
        if value not in spec.options:
            raise Invalid(
                f"{label} must be one of: {', '.join(map(str, spec.options))}."
            )
        return value
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise Invalid(f"{label} must be true or false.")
        return value
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise Invalid(f"{label} must be a number.")
        if spec.integer and value != int(value):
            raise Invalid(f"{label} must be a whole number.")
        value = int(value) if spec.integer else round(float(value), 2)
        if (spec.minimum is not None and value < spec.minimum) or (
            spec.maximum is not None and value > spec.maximum
        ):
            raise Invalid(
                f"{label} must be between {spec.minimum:g} and {spec.maximum:g}."
            )
        return value
    if spec.kind == "ref":
        if isinstance(value, bool) or not isinstance(value, int):
            raise Invalid(f"{label} must reference a resource.")
        return value
    if spec.kind == "strings":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise Invalid(f"{label} must be a list of text.")
        cleaned = [v.replace("\x00", "").strip() for v in value]
        cleaned = list(dict.fromkeys(v for v in cleaned if v))
        if len(cleaned) > spec.max_items or any(
            len(v) > spec.max_length for v in cleaned
        ):
            raise Invalid(
                f"{label} allows {spec.max_items} entries of up to {spec.max_length} characters."
            )
        return cleaned
    if spec.kind == "list":
        if not isinstance(value, list) or len(value) > spec.max_items:
            raise Invalid(f"{label} allows at most {spec.max_items} entries.")
        return [
            _clean_object(spec.items, item, f"{label} {i}: ")
            for i, item in enumerate(value, 1)
        ]
    raise AssertionError(spec.kind)


def _clean_object(specs: tuple[F, ...], given: Any, where: str = "") -> dict[str, Any]:
    if not isinstance(given, dict):
        raise Invalid(f"{where}expected an object.")
    unknown = set(given) - {spec.key for spec in specs}
    if unknown:
        raise Invalid(f"{where}unknown setting {min(unknown)!r}.")
    return {
        spec.key: _clean_value(spec, given.get(spec.key, spec.default), where)
        for spec in specs
    }


def clean_properties(
    rtype: ResourceType,
    given: dict[str, Any],
    world: World,
    parent: Row | None,
    self_id: int | None = None,
    old: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a full set of properties, as Azure Resource Manager would on save."""
    if old is not None:
        given = {**old, **given}
    props = _clean_object(rtype.fields, given)
    for spec in rtype.fields:
        if (
            old is not None
            and not spec.updatable
            and props[spec.key] != old.get(spec.key)
        ):
            raise Conflict(f"{spec.label} can't be changed after creation.")
        if spec.kind == "ref" and props[spec.key] is not None:
            target = world.get(props[spec.key])
            if (
                target is None
                or target.resource_type not in spec.refs
                or target.id == self_id
            ):
                raise Invalid(f"{spec.label}: the referenced resource doesn't exist.")
    context = RuleContext(world, parent, self_id, old)
    for rule in rtype.rules:
        rule(props, context)
    return props
