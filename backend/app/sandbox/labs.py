"""Guided labs: scenarios, tasks and the deterministic checks that grade them.

A check reads only stored resources in the lab's own resource group and returns None
when it passes, or feedback saying what is wrong and why without giving the full
answer. Checks are plain code, so the same state always gets the same grade, and no
model output can change it. Hints are revealed one at a time, on request.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.sandbox.catalog import (
    INFERENCE_ROLES,
    MODELS,
    Row,
    World,
    data_zone,
    region_label,
)
from app.sandbox.simulate import fingerprint, vector_fields, vector_mismatch


@dataclass
class LabState:
    world: World
    group: Row | None

    def all(self, resource_type: str) -> list[Row]:
        if self.group is None:
            return []
        return [
            row
            for row in self.world.descendants(self.group.id)
            if row.resource_type == resource_type and row.state != "soft_deleted"
        ]

    def named(self, resource_type: str, name: str) -> Row | None:
        return next(
            (
                row
                for row in self.all(resource_type)
                if row.name.lower() == name.lower()
            ),
            None,
        )

    def ref(self, row: Row, key: str) -> Row | None:
        return self.world.get(row.properties.get(key))

    def current(self, row: Row) -> bool:
        """Its last test ran on today's configuration of the whole sandbox."""
        test = row.outputs.get("last_test") or {}
        return bool(test) and test.get("fingerprint") == fingerprint(self.world)


Test = Callable[[LabState], str | None]


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    test: Test
    hints: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    checks: tuple[Check, ...]


@dataclass(frozen=True)
class Seed:
    """A starter resource. Property values written "@name" refer to an earlier seed."""

    resource_type: str
    name: str
    parent: str | None
    properties: dict[str, Any] = field(default_factory=dict)
    load_sample: bool = False


@dataclass(frozen=True)
class Lab:
    id: str
    title: str
    objective: str
    syllabus: tuple[str, ...]
    prerequisites: tuple[str, ...]
    minutes: int
    scenario: str
    expected_outcome: str
    instructions: tuple[str, ...]
    resource_group: str
    tasks: tuple[Task, ...]
    completion: str
    docs: tuple[tuple[str, str], ...]
    approximations: tuple[str, ...] = ()
    seeds: tuple[Seed, ...] = ()

    @property
    def checks(self) -> list[Check]:
        return [check for task in self.tasks for check in task.checks]


_LEARN = "https://learn.microsoft.com/en-us/azure/"


def _group_exists(name: str) -> Test:
    def test(s: LabState) -> str | None:
        if s.group is None:
            return (
                f"No resource group named {name} exists yet. Labs only look inside "
                "their own resource group."
            )
        return None

    return test


# --- Lab 1: Foundry resource and project ---


def _eu_accounts(s: LabState) -> list[Row]:
    return [
        r
        for r in s.all("foundry_resource")
        if data_zone(r.properties["region"]) == "EU"
    ]


def _foundry_in_eu(s: LabState) -> str | None:
    accounts = s.all("foundry_resource")
    if not accounts:
        return "There's no Foundry resource in rg-lab-foundry yet."
    if not _eu_accounts(s):
        account = accounts[0]
        return (
            f"{account.name} is in {region_label(account.properties['region'])}, which "
            "is outside the EU, so data would be stored outside it. A resource's region "
            "is fixed at creation, so this needs a new resource."
        )
    return None


def _project_on_eu_account(s: LabState) -> str | None:
    eu = {row.id for row in _eu_accounts(s)}
    projects = s.all("foundry_project")
    if any(project.parent_id in eu for project in projects):
        return None
    if projects:
        return "Your project belongs to a Foundry resource outside the EU."
    return "Create a project inside the Foundry resource. Apps connect to a project, not to the resource group."


FOUNDRY_SETUP = Lab(
    id="foundry-setup",
    title="Set up a Foundry resource and project for an EU workload",
    objective="Plan the Azure resources behind a Foundry solution: a resource group, a Foundry resource in a region that meets data residency rules, and a project that apps connect to.",
    syllabus=(
        "Design Azure infrastructure for AI apps and agent-based solutions",
        "Configure an application to connect to a Foundry project",
    ),
    prerequisites=("None. This is the first lab.",),
    minutes=10,
    scenario="Contoso Health (a fictional company) is building a summarization app for clinic notes. Its compliance team requires that the AI resources and their data stay within the European Union. You set up the foundation the developers will build on.",
    expected_outcome="A resource group named rg-lab-foundry holding a Foundry resource in an EU region, with one Foundry project inside it.",
    instructions=(
        "Create a resource group named rg-lab-foundry. Its own region only stores metadata.",
        "Create a Foundry resource in that resource group, choosing a region that satisfies the residency requirement.",
        "Open the Foundry resource and add a project to it.",
        "Select Validate to check your work. If you need to replace a resource, remember what happens to deleted AI resource names.",
    ),
    resource_group="rg-lab-foundry",
    tasks=(
        Task(
            "group",
            "Create the resource group",
            (
                Check(
                    "group-exists",
                    "Resource group rg-lab-foundry exists",
                    _group_exists("rg-lab-foundry"),
                    (
                        "Use Create a resource, then Resource group. The name must match exactly.",
                    ),
                    "Resource groups hold resources that share a lifecycle, so you can manage, secure and delete them together.",
                ),
            ),
        ),
        Task(
            "resource",
            "Create the Foundry resource",
            (
                Check(
                    "foundry-in-eu",
                    "A Foundry resource in an EU region",
                    _foundry_in_eu,
                    (
                        "Data residency is decided by the region you pick when you create the resource.",
                        "Choose a region in the EU data zone. If you delete a resource to replace it, its name stays reserved for 48 hours unless you purge it under Deleted resources.",
                    ),
                    "A Foundry resource's region decides where its data is stored. Region can't be changed later, so it's a design decision, not a setting.",
                ),
            ),
        ),
        Task(
            "project",
            "Create a project",
            (
                Check(
                    "project",
                    "A Foundry project on the EU resource",
                    _project_on_eu_account,
                    (
                        "Open the Foundry resource's overview and add a child resource of type Foundry project.",
                    ),
                    "Projects are where agents, connections and evaluations live. Applications use the project endpoint to reach them.",
                ),
            ),
        ),
    ),
    completion="You planned a Foundry deployment around a residency requirement: the region decision comes first, because it can't be changed afterwards.",
    docs=(
        (
            "Create a Foundry resource",
            _LEARN + "ai-foundry/how-to/create-resource-template",
        ),
        ("Create a project", _LEARN + "ai-foundry/how-to/create-projects"),
        (
            "Recover or purge deleted resources",
            _LEARN + "ai-services/recover-purge-resources",
        ),
    ),
    approximations=(
        "Only a few regions are simulated, and each is treated as either in the EU data zone or not.",
    ),
)


# --- Lab 2: model deployment ---

_SMALL_CHAT = ("gpt-4o-mini", "gpt-4.1-mini")


def _support_deployment(s: LabState) -> Row | None:
    account = s.named("foundry_resource", "contoso-chat-ai")
    if account is None:
        return None
    return next(
        (
            d
            for d in s.world.children(account.id, "model_deployment")
            if d.name.lower() == "support-chat"
        ),
        None,
    )


def _with_deployment(test: Callable[[dict[str, Any]], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        deployment = _support_deployment(s)
        if deployment is None:
            return "No deployment named support-chat exists on contoso-chat-ai yet."
        return test(deployment.properties)

    return run


def _small_model(props: dict[str, Any]) -> str | None:
    model = props["model"]
    if MODELS[model].kind == "embedding":
        return f"{model} is an embedding model. It turns text into vectors and can't answer chat requests."
    if model not in _SMALL_CHAT:
        return f"{model} would work, but it costs more per token than short support answers need."
    return None


_TYPE_FEEDBACK = {
    "GlobalStandard": "Global Standard may process prompts in any Azure region, which breaks the EU-only processing rule.",
    "Standard": "Standard (regional) keeps processing in Sweden Central only. The scenario wants capacity across EU regions.",
    "GlobalBatch": "Batch deployments process requests asynchronously, hours later. A chat app needs real-time answers.",
    "DataZoneBatch": "Batch deployments process requests asynchronously, hours later. A chat app needs real-time answers.",
}


def _deployment_type(props: dict[str, Any]) -> str | None:
    kind = props["deployment_type"]
    if kind == "DataZoneStandard":
        return None
    return _TYPE_FEEDBACK.get(
        kind,
        "Provisioned deployments reserve throughput that's billed even when idle. The scenario asks for pay-per-token pricing.",
    )


def _capacity(props: dict[str, Any]) -> str | None:
    capacity = props["capacity"]
    if capacity < 50:
        return f"{capacity}K tokens per minute is below the expected peak, so busy periods would get 429 (rate limit) errors."
    if capacity > 100:
        return f"{capacity}K tokens per minute reserves more quota than the scenario allows, leaving less for other deployments in the region."
    return None


def _upgrade(props: dict[str, Any]) -> str | None:
    option = props["version_upgrade_option"]
    if option == "OnceNewDefaultVersionAvailable":
        return "This policy upgrades within weeks of a new default version, before the team has re-tested."
    if option == "NoAutoUpgrade":
        return "With no automatic upgrade, the deployment stops working when its version retires."
    return None


MODEL_DEPLOYMENT = Lab(
    id="model-deployment",
    title="Deploy a chat model with the right type, capacity and upgrade policy",
    objective="Choose a model, deployment type, capacity and version upgrade policy from business requirements, and see how quota limits deployments.",
    syllabus=(
        "Choose an appropriate model for each task, including large language models (LLMs), small language models, multimodal models, and Foundry Tools",
        "Choose appropriate deployment options",
        "Configure model and agent deployments",
        "Manage quotas, scaling, rate limits, and cost footprints for model and agent workloads",
    ),
    prerequisites=(
        "Foundry resources and projects (lab: Set up a Foundry resource and project).",
    ),
    minutes=15,
    scenario="Contoso's customer support app answers short questions in chat. Requirements: a small, cost-efficient chat model; prompts processed only inside the EU, but with more capacity and availability than a single region gives; pay per token; a peak of about 50,000 tokens per minute with a budget cap of 100,000; and because the team re-tests before any model change, the deployment must keep its version until that version retires.",
    expected_outcome="A deployment named support-chat on contoso-chat-ai that meets every requirement.",
    instructions=(
        "Start the lab: it creates rg-lab-deploy with the Foundry resource contoso-chat-ai in Sweden Central.",
        "Open contoso-chat-ai and add a model deployment named support-chat. The app calls the deployment by this name.",
        "Pick the model, deployment type, capacity and upgrade policy from the scenario. Model and deployment type can't be changed later.",
        "Validate. To fix the model or type, delete the deployment and create it again.",
    ),
    resource_group="rg-lab-deploy",
    tasks=(
        Task(
            "deploy",
            "Deploy the model",
            (
                Check(
                    "deployment-exists",
                    "Deployment support-chat exists on contoso-chat-ai",
                    _with_deployment(lambda props: None),
                    (
                        "Open contoso-chat-ai and add a child resource of type Model deployment named support-chat.",
                    ),
                    "Apps reference a deployment by name, so the name is part of the app's configuration.",
                ),
                Check(
                    "model",
                    "A small, cost-efficient chat model",
                    _with_deployment(_small_model),
                    (
                        "Compare chat models by size. Short support answers rarely need the largest model.",
                        "Look for the mini variants of the chat models.",
                    ),
                    "Small language models answer simple, high-volume requests at a fraction of a large model's cost and latency.",
                ),
                Check(
                    "deployment-type",
                    "A deployment type that keeps processing in the EU across regions, billed per token",
                    _with_deployment(_deployment_type),
                    (
                        "Deployment types differ in where prompts are processed: any region, a data zone, or one region.",
                        "A data zone groups the regions of one geography, such as the EU.",
                    ),
                    "Data Zone Standard processes data only within the data zone while drawing on capacity across its regions, and bills per token.",
                ),
            ),
        ),
        Task(
            "operate",
            "Size and maintain it",
            (
                Check(
                    "capacity",
                    "Capacity covers the peak without exceeding the budget",
                    _with_deployment(_capacity),
                    (
                        "Standard capacity is set in thousands of tokens per minute (TPM).",
                    ),
                    "Capacity is a rate limit: requests above it get 429 errors, and capacity you assign is quota others in the region can't use.",
                ),
                Check(
                    "upgrade",
                    "Version upgrade policy keeps the version until it retires",
                    _with_deployment(_upgrade),
                    (
                        "Three policies exist: upgrade when a new default arrives, upgrade at expiry, or never.",
                    ),
                    "Upgrading at expiry gives the team the whole version lifetime to re-test, without the deployment stopping when the version retires.",
                ),
            ),
        ),
    ),
    completion="You turned business requirements into deployment settings: model size for cost, deployment type for data residency, capacity for rate limits, and upgrade policy for change control.",
    docs=(
        (
            "Deployment types",
            _LEARN + "ai-foundry/foundry-models/concepts/deployment-types",
        ),
        (
            "Model versions and upgrades",
            _LEARN + "ai-foundry/openai/how-to/working-with-models",
        ),
        ("Manage quota", _LEARN + "ai-foundry/openai/how-to/quota"),
    ),
    approximations=(
        "Quota is a flat simulated limit of 300K TPM per model, deployment type and region.",
        "Every model is treated as available in every simulated region.",
    ),
    seeds=(
        Seed("resource_group", "rg-lab-deploy", None, {"region": "swedencentral"}),
        Seed(
            "foundry_resource",
            "contoso-chat-ai",
            "rg-lab-deploy",
            {"region": "swedencentral"},
        ),
        Seed(
            "foundry_project",
            "support-app",
            "contoso-chat-ai",
            {"display_name": "Support app"},
        ),
    ),
)


# --- Lab 3: content safety ---

_THRESHOLD_KEYS = [
    (f"{category}_{direction}", f"{label}: {noun}")
    for category, label in (
        ("hate", "Hate and fairness"),
        ("sexual", "Sexual"),
        ("violence", "Violence"),
        ("self_harm", "Self-harm"),
    )
    for direction, noun in (("prompt", "prompts"), ("completion", "completions"))
]


def _tutor_chat(s: LabState) -> Row | None:
    account = s.named("foundry_resource", "fabrikam-tutor-ai")
    if account is None:
        return None
    return next(
        (
            d
            for d in s.world.children(account.id, "model_deployment")
            if d.name == "tutor-chat"
        ),
        None,
    )


def _evaluated_filter(s: LabState) -> Row | None:
    """The filter tutor-chat uses, else the newest filter on the resource."""
    deployment = _tutor_chat(s)
    if deployment is not None:
        assigned = s.ref(deployment, "content_filter")
        if assigned is not None:
            return assigned
    filters = s.all("content_filter")
    return filters[-1] if filters else None


def _with_filter(test: Callable[[dict[str, Any]], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        content_filter = _evaluated_filter(s)
        if content_filter is None:
            return "There's no custom content filter on fabrikam-tutor-ai yet. Deployments without one use DefaultV2."
        return test(content_filter.properties)

    return run


def _strictest(props: dict[str, Any]) -> str | None:
    loose = [label for key, label in _THRESHOLD_KEYS if props[key] != "Low"]
    if loose:
        return (
            f"{len(loose)} of 8 thresholds still let low-severity content through: "
            f"{', '.join(loose)}."
        )
    return None


def _filter_assigned(s: LabState) -> str | None:
    deployment = _tutor_chat(s)
    if deployment is None:
        return (
            "The tutor-chat deployment no longer exists. Reset the lab to restore it."
        )
    if s.ref(deployment, "content_filter") is None:
        return "tutor-chat still uses DefaultV2, which blocks only medium and high severity and doesn't check documents for hidden instructions."
    return None


CONTENT_SAFETY = Lab(
    id="content-safety",
    title="Configure guardrails for a homework helper used by teenagers",
    objective="Configure a content filter's severity thresholds, Prompt Shields and blocklist to meet a safety requirement, and apply it to a model deployment.",
    syllabus=(
        "Configure safety filters, guardrails, risk detection, and content moderation",
    ),
    prerequisites=("Model deployments (lab: Deploy a chat model).",),
    minutes=15,
    scenario='Fabrikam (a fictional company) runs a homework helper for students aged 13 to 17. The safety review requires: the strictest filtering for hate, sexual, violence and self-harm content, on both what students type and what the model writes; detection of attempts to talk the model out of its rules; detection of instructions hidden inside uploaded worksheets; and blocking any request containing the phrase "exam leak".',
    expected_outcome="A custom content filter on fabrikam-tutor-ai that meets the review, assigned to the tutor-chat deployment.",
    instructions=(
        "Start the lab: it creates rg-lab-safety with fabrikam-tutor-ai and a tutor-chat deployment that uses the default filter.",
        "On tutor-chat, use Test prompt to see what the default filter lets through.",
        "Add a content filter to fabrikam-tutor-ai and configure it for the review.",
        "Assign the filter to tutor-chat, test again, then Validate.",
    ),
    resource_group="rg-lab-safety",
    tasks=(
        Task(
            "filter",
            "Create the content filter",
            (
                Check(
                    "thresholds",
                    "Strictest threshold for every harm category, on prompts and completions",
                    _with_filter(_strictest),
                    (
                        "A threshold names the lowest severity that gets blocked.",
                        "The strictest setting blocks low, medium and high severity alike.",
                    ),
                    "Thresholds trade safety for helpfulness: the strictest setting also blocks some harmless content, such as a history question about a battle, which is acceptable for a young audience.",
                ),
                Check(
                    "jailbreak",
                    "Detects user prompt attacks (jailbreaks)",
                    _with_filter(
                        lambda p: (
                            None
                            if p["jailbreak_shield"]
                            else "Prompt Shields for user prompt attacks is off, so attempts to talk the model out of its rules aren't detected."
                        )
                    ),
                    ("Look at the Prompt Shields settings.",),
                    "Prompt Shields classifies prompts that try to override the system message, a different signal from harm categories.",
                ),
                Check(
                    "indirect",
                    "Detects indirect attacks in documents",
                    _with_filter(
                        lambda p: (
                            None
                            if p["indirect_attack_shield"]
                            else "Indirect attack detection is off. Worksheets students upload can carry hidden instructions the model would follow."
                        )
                    ),
                    (
                        "Instructions can also arrive inside documents rather than from the user.",
                    ),
                    "Indirect (document) attacks hide instructions in content the model reads. Detecting them is off by default.",
                ),
                Check(
                    "blocklist",
                    'Blocks the phrase "exam leak"',
                    _with_filter(
                        lambda p: (
                            None
                            if any(
                                t.lower() == "exam leak" for t in p["blocklist_terms"]
                            )
                            else "Requests mentioning the phrase from the review aren't blocked yet."
                        )
                    ),
                    (
                        "Harm classifiers don't know your organization's own forbidden terms. Use a custom blocklist.",
                    ),
                    "Blocklists catch exact terms that matter to your organization but aren't harmful in general.",
                ),
            ),
        ),
        Task(
            "apply",
            "Apply it",
            (
                Check(
                    "assigned",
                    "tutor-chat uses the custom filter",
                    _filter_assigned,
                    (
                        "A content filter does nothing until a deployment uses it. Edit the deployment's settings.",
                    ),
                    "Filters are applied per deployment, so one resource can serve audiences with different safety needs.",
                ),
            ),
        ),
    ),
    completion="You configured guardrails from a policy: harm thresholds per direction, Prompt Shields for direct and indirect attacks, and a blocklist, applied to the deployment that serves the audience.",
    docs=(
        ("Content filtering", _LEARN + "ai-foundry/openai/concepts/content-filter"),
        (
            "Default safety policies",
            _LEARN + "ai-foundry/openai/concepts/default-safety-policies",
        ),
        (
            "Prompt Shields",
            _LEARN + "ai-services/content-safety/concepts/jailbreak-detection",
        ),
    ),
    approximations=(
        "Test prompts carry fixed, simulated classifier results; no content is analyzed.",
        "Only the prompt side is exercised by tests, although completion thresholds are graded.",
    ),
    seeds=(
        Seed("resource_group", "rg-lab-safety", None, {"region": "francecentral"}),
        Seed(
            "foundry_resource",
            "fabrikam-tutor-ai",
            "rg-lab-safety",
            {"region": "francecentral"},
        ),
        Seed(
            "model_deployment",
            "tutor-chat",
            "fabrikam-tutor-ai",
            {
                "model": "gpt-4o-mini",
                "model_version": "2024-07-18",
                "deployment_type": "DataZoneStandard",
                "capacity": 20,
            },
        ),
    ),
)


# --- Lab 4: search index ---


def _search_service(s: LabState) -> Row | None:
    services = s.all("search_service")
    return next(
        (svc for svc in services if svc.properties["tier"] != "free"),
        services[0] if services else None,
    )


def _with_service(test: Callable[[Row], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        service = _search_service(s)
        if service is None:
            return "There's no Azure AI Search service in rg-lab-search yet."
        return test(service)

    return run


def _manuals_index(s: LabState) -> Row | None:
    service = _search_service(s)
    if service is None:
        return None
    return next(
        (
            i
            for i in s.world.children(service.id, "search_index")
            if i.name == "manuals-index"
        ),
        None,
    )


def _with_index(test: Callable[[LabState, Row], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        index = _manuals_index(s)
        if index is None:
            return "No index named manuals-index exists on your search service in rg-lab-search."
        return test(s, index)

    return run


def _vectors(s: LabState, index: Row) -> str | None:
    if not vector_fields(index):
        return "manuals-index has no vector field, so it can only match the words people type."
    if s.ref(index, "vectorizer") is None:
        return "manuals-index has no vectorizer, so the service can't turn query text into vectors and every app would have to embed queries itself."
    return vector_mismatch(s.world, index)


def _category(s: LabState, index: Row) -> str | None:
    field_ = next(
        (f for f in index.properties["fields"] if f["name"].lower() == "category"), None
    )
    if field_ is None:
        return "manuals-index has no category field to filter on."
    if not (field_["filterable"] and field_["facetable"]):
        return "The category field must support filtering and show counts per value (facets)."
    return None


SEARCH_INDEX = Lab(
    id="search-index",
    title="Design an Azure AI Search index for hybrid and semantic retrieval",
    objective="Size a search service for production, and design an index whose fields, vector configuration and semantic configuration support hybrid retrieval for grounding.",
    syllabus=(
        "Choose an appropriate method for retrieval and indexing",
        "Configure semantic search, hybrid search, and vector search for grounding",
        "Ingest and index content, such as documents, images, audio, and video",
    ),
    prerequisites=(
        "Model deployments, including embedding models (lab: Deploy a chat model).",
    ),
    minutes=20,
    scenario="Northwind Traders (a fictional company) wants an assistant that answers from its product manuals. Users phrase questions in their own words, so retrieval must match meaning as well as keywords and re-rank results for relevance. The service must be covered by the query SLA. Users also filter by product category and see how many manuals each category has. An embedding deployment, embed-small, already exists.",
    expected_outcome="A production-ready search service in rg-lab-search with an index named manuals-index for hybrid search, vectorization, semantic ranking and category filters.",
    instructions=(
        "Start the lab: it creates rg-lab-search with northwind-ai and the embedding deployment embed-small.",
        "Create an Azure AI Search service in rg-lab-search, sized for the SLA, with semantic ranker enabled.",
        "Add an index named manuals-index with a key, searchable title and content fields, a category field, and a vector field that matches embed-small.",
        "Set embed-small as the index's vectorizer and add a semantic configuration, then Validate. Existing index fields can't be changed, only added.",
    ),
    resource_group="rg-lab-search",
    tasks=(
        Task(
            "service",
            "Create the search service",
            (
                Check(
                    "tier",
                    "A paid tier",
                    _with_service(
                        lambda svc: (
                            None
                            if svc.properties["tier"] != "free"
                            else "The Free tier has no SLA and can't add replicas."
                        )
                    ),
                    ("Compare what each tier offers for production workloads.",),
                    "The Free tier is for trials: shared, limited and without an SLA.",
                ),
                Check(
                    "replicas",
                    "Enough replicas for the query SLA",
                    _with_service(
                        lambda svc: (
                            None
                            if svc.properties["replicas"] >= 2
                            else f"With {svc.properties['replicas']} replica, queries aren't covered by the SLA."
                        )
                    ),
                    (
                        "Replicas are copies of the index that serve queries. The SLA depends on how many there are.",
                    ),
                    "Two replicas give a query SLA and three a query and indexing SLA, because a service needs spare copies during maintenance.",
                ),
                Check(
                    "semantic",
                    "Semantic ranker enabled",
                    _with_service(
                        lambda svc: (
                            None
                            if svc.properties["semantic_ranker"] != "disabled"
                            else "Semantic ranker is disabled, so results can't be re-ranked for relevance."
                        )
                    ),
                    (
                        "Re-ranking is a service-level feature that you turn on before any index can use it.",
                    ),
                    "Semantic ranker re-scores the top results with a language model, which improves relevance for natural-language questions.",
                ),
            ),
        ),
        Task(
            "index",
            "Design the index",
            (
                Check(
                    "index-exists",
                    "Index manuals-index exists",
                    _with_index(lambda s, index: None),
                    (
                        "Open your search service and add a child resource of type Search index.",
                    ),
                    "Apps and agents query an index by name.",
                ),
                Check(
                    "vectors",
                    "A vector field that matches the vectorizer",
                    _with_index(_vectors),
                    (
                        "A vector field is Collection(Edm.Single) and has a fixed number of dimensions.",
                        "Check the default vector dimensions on embed-small's overview. Every vector must have exactly that many.",
                    ),
                    "A vector field's dimensions must equal the embedding model's output, or indexing and querying fail. A vectorizer lets the service embed query text itself.",
                ),
                Check(
                    "semantic-config",
                    "A semantic configuration over the content",
                    _with_index(
                        lambda s, index: (
                            None
                            if index.properties["semantic_content_fields"]
                            else "manuals-index has no semantic configuration, so semantic ranker has nothing to read."
                        )
                    ),
                    (
                        "A semantic configuration tells semantic ranker which fields hold the title and the content.",
                    ),
                    "Semantic ranker reads only the fields named in the semantic configuration.",
                ),
                Check(
                    "category",
                    "Category supports filters and facets",
                    _with_index(_category),
                    (
                        "Filtering and counting per value are separate field attributes.",
                    ),
                    "Field attributes are fixed at creation: filterable powers filters, facetable powers counts per value.",
                ),
            ),
        ),
    ),
    completion="You designed an index for hybrid retrieval: keyword and vector fields together, a vectorizer that matches the embedding model, semantic ranking, and filterable metadata, on a service sized for its SLA.",
    docs=(
        ("Choose a tier", _LEARN + "search/search-sku-tier"),
        ("Create a vector index", _LEARN + "search/vector-search-how-to-create-index"),
        ("Semantic ranking", _LEARN + "search/semantic-search-overview"),
        ("Hybrid search", _LEARN + "search/hybrid-search-overview"),
    ),
    approximations=(
        "Each index has one vector profile, and vectorizers produce the model's default dimensions only.",
    ),
    seeds=(
        Seed("resource_group", "rg-lab-search", None, {"region": "eastus2"}),
        Seed(
            "foundry_resource", "northwind-ai", "rg-lab-search", {"region": "eastus2"}
        ),
        Seed(
            "model_deployment",
            "embed-small",
            "northwind-ai",
            {
                "model": "text-embedding-3-small",
                "model_version": "1",
                "deployment_type": "Standard",
                "capacity": 50,
            },
        ),
    ),
)


# --- Lab 5: RAG agent ---


def _project(s: LabState) -> Row | None:
    return s.named("foundry_project", "support-project")


def _rag_connection(s: LabState) -> Row | None:
    project = _project(s)
    service = s.named("search_service", "woodgrove-search")
    if project is None or service is None:
        return None
    return next(
        (
            c
            for c in s.world.children(project.id, "foundry_connection")
            if c.properties["target"] == service.id
        ),
        None,
    )


def _policy_agent(s: LabState) -> Row | None:
    project = _project(s)
    if project is None:
        return None
    return next(
        (a for a in s.world.children(project.id, "agent") if a.name == "policy-agent"),
        None,
    )


def _with_agent(test: Callable[[LabState, Row], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        agent = _policy_agent(s)
        if agent is None:
            return "No agent named policy-agent exists in support-project yet."
        return test(s, agent)

    return run


def _search_tool(s: LabState, agent: Row) -> str | None:
    props = agent.properties
    index = s.ref(agent, "search_index")
    if not props["search_tool"]:
        return "policy-agent has no Azure AI Search tool, so it answers from training data and may invent policies."
    if index is None or index.name != "policies-index":
        return "The search tool doesn't use policies-index, where the policies are indexed."
    return None


_QUERY_FEEDBACK = {
    "simple": 'Keyword search misses paraphrases, such as "send back" for "return".',
    "semantic": "Semantic ranking re-ranks keyword results only. It doesn't add matches by meaning.",
    "vector": "Vector-only search can miss exact terms, such as product codes.",
    "vector_simple_hybrid": "Hybrid search combines keyword and vector matches, but skips the re-ranking the scenario asks for.",
}


def _top_k(s: LabState, agent: Row) -> str | None:
    top_k = agent.properties["top_k"]
    if top_k < 3:
        return f"Retrieving {top_k} document(s) risks missing the passage that holds the answer."
    if top_k > 10:
        return f"Retrieving {top_k} documents fills the prompt with loosely related text and raises token cost."
    return None


_CITE = re.compile(
    r"\b(cite|cites|citing|citation|citations|source|sources)\b", re.IGNORECASE
)


def _tested(s: LabState, agent: Row) -> str | None:
    test = agent.outputs.get("last_test") or {}
    if not s.current(agent):
        return "Run a test question on policy-agent after your latest change."
    if not test.get("grounded"):
        return f"The last test wasn't grounded in retrieved documents: {test.get('error') or test.get('answer')}"
    return None


RAG_AGENT = Lab(
    id="rag-agent",
    title="Ground an agent in your search index (retrieval-augmented generation)",
    objective="Connect a Foundry project to Azure AI Search with keyless authentication and build an agent that retrieves, ranks and cites indexed documents.",
    syllabus=(
        "Implement retrieval-augmented generation (RAG) in an application",
        "Build agents that integrate retrieval, function-calling, and conversation memory",
        "Integrate agent tools, including APIs, knowledge stores, search, content understanding, and custom functions",
        "Connect retrieval pipelines directly to workflows and agent tools",
    ),
    prerequisites=(
        "Search indexes (lab: Design an Azure AI Search index).",
        "Model deployments (lab: Deploy a chat model).",
    ),
    minutes=20,
    scenario="Woodgrove (a fictional retailer) has indexed its customer policies in policies-index. Support staff need an agent that answers only from those policies, with the best relevance available (keyword and vector matches combined, then re-ranked), and that tells staff which policy each answer comes from. Security has disabled key-based authentication on the search service.",
    expected_outcome="An agent named policy-agent in support-project that retrieves from policies-index through a keyless connection and gives a grounded, cited answer in a test.",
    instructions=(
        "Start the lab: it creates rg-lab-rag with the Foundry resource, project, chat and embedding deployments, and a search service with a loaded index.",
        "In support-project, add a connection to woodgrove-search with the right authentication.",
        "Add an agent named policy-agent with the chat deployment and the Azure AI Search tool on policies-index.",
        "Choose the query type and number of documents from the scenario, and write instructions that ask the agent to cite its sources.",
        "Test the agent with a sample question, then Validate.",
    ),
    resource_group="rg-lab-rag",
    tasks=(
        Task(
            "connect",
            "Connect the project to search",
            (
                Check(
                    "connection",
                    "support-project has a connection to woodgrove-search",
                    lambda s: (
                        None
                        if _rag_connection(s)
                        else "support-project has no connection to woodgrove-search yet."
                    ),
                    (
                        "Agents reach other resources through the project's connections.",
                    ),
                    "Connections hold the target and authentication once, so every agent and tool in the project can reuse them.",
                ),
                Check(
                    "keyless",
                    "The connection authenticates without keys",
                    lambda s: (
                        None
                        if (c := _rag_connection(s))
                        and c.properties["auth_type"] == "EntraId"
                        else "The connection uses an API key, but woodgrove-search has key-based authentication disabled, so calls would fail with 401."
                    ),
                    ("Look at the search service's Key-based authentication setting.",),
                    "Microsoft Entra ID authentication uses identities and roles instead of shared keys that can leak.",
                ),
            ),
        ),
        Task(
            "agent",
            "Build the agent",
            (
                Check(
                    "agent-exists",
                    "Agent policy-agent exists",
                    _with_agent(lambda s, agent: None),
                    ("Open support-project and add a child resource of type Agent.",),
                    "An agent combines a model, instructions and tools.",
                ),
                Check(
                    "search-tool",
                    "The agent retrieves from policies-index",
                    _with_agent(_search_tool),
                    (
                        "Turn on the Azure AI Search tool and pick the connection and the index.",
                    ),
                    "Retrieval puts the relevant policy text into the prompt, so the model answers from it instead of from memory.",
                ),
                Check(
                    "query-type",
                    "The query type gives the best relevance",
                    _with_agent(
                        lambda s, agent: _QUERY_FEEDBACK.get(
                            agent.properties["query_type"]
                        )
                    ),
                    (
                        "The scenario names three ingredients: keyword matches, vector matches and re-ranking.",
                        "Re-ranking needs semantic ranker on the service and a semantic configuration on the index, which both exist here.",
                    ),
                    "Hybrid search merges keyword and vector results, and semantic ranking re-orders the merged results by meaning.",
                ),
                Check(
                    "top-k",
                    "A sensible number of retrieved documents",
                    _with_agent(_top_k),
                    (
                        "Too few documents can miss the answer; too many add noise and cost.",
                    ),
                    "Retrieving a handful of top documents balances recall against prompt size.",
                ),
                Check(
                    "citations",
                    "Instructions ask the agent to cite its sources",
                    _with_agent(
                        lambda s, agent: (
                            None
                            if _CITE.search(agent.properties["instructions"])
                            else "The instructions don't ask the agent to say which policy an answer comes from."
                        )
                    ),
                    (
                        "Staff need to know where each answer came from. Say so in the instructions.",
                    ),
                    "Asking for citations makes answers checkable and discourages answers that the retrieved text doesn't support.",
                ),
            ),
        ),
        Task(
            "test",
            "Test it",
            (
                Check(
                    "grounded-test",
                    "A grounded test answer on the current configuration",
                    _with_agent(_tested),
                    (
                        "Use Test on policy-agent with a policy question, not the jailbreak sample.",
                    ),
                    "Testing end to end catches mistakes no single setting shows, such as authentication or vector mismatches.",
                ),
            ),
        ),
    ),
    completion="You built a RAG agent: a keyless connection to search, hybrid retrieval with semantic ranking, a bounded number of documents, and instructions that make answers cite their source.",
    docs=(
        (
            "Azure AI Search tool for agents",
            _LEARN + "ai-foundry/agents/how-to/tools/azure-ai-search",
        ),
        (
            "RAG with Azure AI Search",
            _LEARN + "search/retrieval-augmented-generation-overview",
        ),
        ("Add a connection", _LEARN + "ai-foundry/how-to/connections-add"),
    ),
    approximations=(
        "Answers come from rules over a built-in five-document corpus; no model or search query runs.",
        "With Entra ID, the project's identity is assumed to hold the Search Index Data Reader role.",
    ),
    seeds=(
        Seed("resource_group", "rg-lab-rag", None, {"region": "westeurope"}),
        Seed(
            "foundry_resource", "woodgrove-ai", "rg-lab-rag", {"region": "westeurope"}
        ),
        Seed(
            "foundry_project",
            "support-project",
            "woodgrove-ai",
            {"display_name": "Support"},
        ),
        Seed(
            "model_deployment",
            "chat",
            "woodgrove-ai",
            {
                "model": "gpt-4o-mini",
                "model_version": "2024-07-18",
                "deployment_type": "DataZoneStandard",
                "capacity": 30,
            },
        ),
        Seed(
            "model_deployment",
            "embed",
            "woodgrove-ai",
            {
                "model": "text-embedding-3-small",
                "model_version": "1",
                "deployment_type": "Standard",
                "capacity": 30,
            },
        ),
        Seed(
            "search_service",
            "woodgrove-search",
            "rg-lab-rag",
            {
                "region": "westeurope",
                "tier": "basic",
                "replicas": 2,
                "semantic_ranker": "free",
                "disable_local_auth": True,
            },
        ),
        Seed(
            "search_index",
            "policies-index",
            "woodgrove-search",
            {
                "fields": [
                    {
                        "name": "id",
                        "type": "Edm.String",
                        "key": True,
                        "searchable": False,
                        "filterable": True,
                    },
                    {"name": "title", "type": "Edm.String"},
                    {"name": "content", "type": "Edm.String"},
                    {
                        "name": "category",
                        "type": "Edm.String",
                        "searchable": False,
                        "filterable": True,
                        "facetable": True,
                    },
                    {
                        "name": "contentVector",
                        "type": "Collection(Edm.Single)",
                        "dimensions": 1536,
                        "retrievable": False,
                    },
                ],
                "vectorizer": "@embed",
                "semantic_title_field": "title",
                "semantic_content_fields": ["content"],
            },
            load_sample=True,
        ),
    ),
)


# --- Lab 6: Document Intelligence ---


def _runs(s: LabState, document: str) -> list[Row]:
    return [
        r for r in s.all("document_analysis") if r.properties["document"] == document
    ]


def _invoice_run(s: LabState) -> str | None:
    runs = _runs(s, "contoso-invoice-1042.pdf")
    if not runs:
        return "No analysis run on contoso-invoice-1042.pdf yet."
    if any(r.outputs["result"]["fields"].get("InvoiceTotal") for r in runs):
        return None
    model = runs[-1].properties["model_id"]
    if model in ("prebuilt-read", "prebuilt-layout"):
        return f"{model} returns text and structure but no typed fields such as InvoiceTotal or DueDate."
    return f"{model} is trained for a different document type, so it finds few invoice fields."


def _handbook_run(s: LabState) -> str | None:
    runs = _runs(s, "employee-handbook.pdf")
    if not runs:
        return "No analysis run on employee-handbook.pdf yet."
    last = runs[-1]
    result = last.outputs["result"]
    for run in runs:
        r = run.outputs["result"]
        if (
            run.properties["model_id"] == "prebuilt-layout"
            and r["content_format"] == "markdown"
            and r["pages_analyzed"] == r["total_pages"]
        ):
            return None
    if last.properties["model_id"] != "prebuilt-layout":
        return f"{last.properties['model_id']} doesn't return the headings and tables that chunking for RAG relies on."
    if result["content_format"] != "markdown":
        return "Plain text output flattens headings and tables, which makes it hard to split the handbook into meaningful chunks."
    return f"Only {result['pages_analyzed']} of {result['total_pages']} pages were analyzed."


DOCUMENT_INTELLIGENCE = Lab(
    id="document-intelligence",
    title="Extract invoice fields and prepare documents for RAG",
    objective="Choose a Document Intelligence pricing tier and the right prebuilt model for each document, and produce structured output for RAG ingestion.",
    syllabus=(
        "Extract information by using multimodal pipelines that combine OCR, layout analysis, and field extraction",
        "Configure RAG ingestion flow, including documents and using optical character recognition (OCR)",
    ),
    prerequisites=("Resource groups (lab: Set up a Foundry resource and project).",),
    minutes=15,
    scenario="Tailspin Toys (a fictional company) needs two document flows. Accounts payable wants the vendor, total and due date pulled out of supplier invoices as fields. HR wants its six-page employee handbook, full of headings and tables, converted into a format that keeps that structure, so it can be split into chunks for a RAG index.",
    expected_outcome="A Document Intelligence resource in rg-lab-docs with one run that extracts invoice fields from contoso-invoice-1042.pdf and one that converts every page of employee-handbook.pdf to structured output.",
    instructions=(
        "Start the lab: it creates the empty resource group rg-lab-docs.",
        "Create a Document Intelligence resource in rg-lab-docs with a pricing tier that can handle the whole handbook.",
        "Add analysis runs to the resource: one for the invoice, one for the handbook. Read each result.",
        "Runs can't be edited. Create a new run after changing the model or the resource's tier, then Validate.",
    ),
    resource_group="rg-lab-docs",
    tasks=(
        Task(
            "resource",
            "Create the resource",
            (
                Check(
                    "resource",
                    "A Document Intelligence resource on a tier that analyzes every page",
                    lambda s: (
                        "There's no Document Intelligence resource in rg-lab-docs yet."
                        if not (rows := s.all("document_intelligence"))
                        else None
                        if any(r.properties["pricing_tier"] == "S0" for r in rows)
                        else "The free tier analyzes only the first two pages of each document, which would cut the handbook short."
                    ),
                    ("Compare the pricing tiers' page limits.",),
                    "The free tier is for trying models: it analyzes only the first two pages of each document.",
                ),
            ),
        ),
        Task(
            "invoice",
            "Extract invoice fields",
            (
                Check(
                    "invoice-fields",
                    "Invoice fields extracted from contoso-invoice-1042.pdf",
                    _invoice_run,
                    (
                        "Text extraction alone gives you characters, not named values.",
                        "Prebuilt models exist for common document types and return typed fields.",
                    ),
                    "The prebuilt invoice model returns typed fields with confidence scores, so no parsing of raw text is needed.",
                ),
            ),
        ),
        Task(
            "handbook",
            "Prepare the handbook for RAG",
            (
                Check(
                    "handbook-markdown",
                    "Every page of employee-handbook.pdf converted with its structure kept",
                    _handbook_run,
                    (
                        "You need a model that recognizes headings and tables, not fields.",
                        "Look at the output content format options.",
                    ),
                    "Layout analysis with markdown output keeps headings and tables, so a RAG pipeline can chunk by section instead of by character count.",
                ),
            ),
        ),
    ),
    completion="You matched models to documents: a prebuilt model for typed invoice fields, and layout analysis with markdown output to keep structure for RAG chunking, on a tier that processes every page.",
    docs=(
        (
            "Document Intelligence models",
            _LEARN + "ai-services/document-intelligence/model-overview",
        ),
        (
            "Layout model and markdown output",
            _LEARN + "ai-services/document-intelligence/prebuilt/layout",
        ),
        (
            "Invoice model",
            _LEARN + "ai-services/document-intelligence/prebuilt/invoice",
        ),
    ),
    approximations=(
        "Results are precomputed for four sample documents.",
        "Markdown output is simulated for prebuilt-layout only.",
    ),
    seeds=(Seed("resource_group", "rg-lab-docs", None, {"region": "eastus"}),),
)


# --- Lab 7: keyless security ---


def _litware(s: LabState) -> tuple[Row | None, Row | None]:
    return s.named("foundry_resource", "litware-ai"), s.named("web_app", "litware-web")


def _with_litware(test: Callable[[LabState, Row, Row], str | None]) -> Test:
    def run(s: LabState) -> str | None:
        account, app = _litware(s)
        if account is None or app is None:
            return "litware-ai or litware-web no longer exists. Reset the lab to restore them."
        return test(s, account, app)

    return run


def _assignments(s: LabState, app: Row) -> list[Row]:
    return [a for a in s.all("role_assignment") if a.properties["principal"] == app.id]


def _least_privilege(s: LabState, account: Row, app: Row) -> str | None:
    assignments = _assignments(s, app)
    if any(
        a.properties["role"] == "Cognitive Services OpenAI User"
        and a.properties["scope"] == account.id
        for a in assignments
    ):
        return None
    if not assignments:
        return "litware-web's identity has no role assignments, so its token would be refused."
    for assignment in assignments:
        role = assignment.properties["role"]
        scope = s.world.get(assignment.properties["scope"])
        if scope is not None and scope.resource_type == "resource_group":
            return "A role at resource group scope applies to every resource in the group, not just litware-ai."
        if role not in INFERENCE_ROLES:
            return f"{role} doesn't allow model inference with Microsoft Entra ID."
        if role != "Cognitive Services OpenAI User":
            return f"{role} allows more than calling models, such as management or key access the app doesn't need."
    return "Assign the role on litware-ai itself."


def _no_broad_roles(s: LabState, account: Row, app: Row) -> str | None:
    broad = [
        a.properties["role"]
        for a in _assignments(s, app)
        if a.properties["role"] in ("Owner", "Contributor")
    ]
    if broad:
        return f"litware-web's identity still holds {', '.join(broad)}, which can change or delete resources."
    return None


def _private_endpoint(s: LabState, account: Row, app: Row) -> str | None:
    endpoints = [
        e for e in s.all("private_endpoint") if e.properties["target"] == account.id
    ]
    if not endpoints:
        return "There's no private endpoint for litware-ai."
    if not any(
        e.properties["virtual_network"].lower() == "litware-vnet" for e in endpoints
    ):
        return "The private endpoint isn't in the virtual network litware-web's traffic goes through."
    return None


def _connection_tested(s: LabState, account: Row, app: Row) -> str | None:
    test = app.outputs.get("last_test") or {}
    if not s.current(app):
        return "Run Test connection on litware-web after your latest change."
    if not test.get("ok"):
        return f"The last connection test failed: {test.get('error')}"
    if not test.get("keyless"):
        return "The last test succeeded with an API key, not with the app's identity."
    return None


KEYLESS_SECURITY = Lab(
    id="keyless-security",
    title="Secure an app's access to Foundry with managed identity and private networking",
    objective="Replace API keys with a managed identity and a least-privilege role, and remove public network access with a private endpoint, without breaking the app.",
    syllabus=(
        "Configure security, including managed identity, private networking, keyless credentials, and role policies",
    ),
    prerequisites=("Foundry resources (lab: Set up a Foundry resource and project).",),
    minutes=20,
    scenario="Litware (a fictional company) has a web app, litware-web, that calls its Foundry resource, litware-ai, with an API key stored in app settings. A security review requires: no keys at all; the app gets only the access it needs to call models, on that one resource; and litware-ai must not be reachable from the internet. The app's outbound traffic already goes through the virtual network litware-vnet. The app must still work at the end.",
    expected_outcome="litware-web calls litware-ai with its managed identity and a least-privilege role, over a private endpoint, with keys and public access disabled.",
    instructions=(
        "Start the lab: it creates rg-lab-secure with litware-ai and litware-web, then run Test connection on litware-web to see the starting point.",
        "Give litware-web an identity, grant it a role, and switch the app to keyless authentication.",
        "Disable key-based authentication and public network access on litware-ai, and add a private endpoint in the right network.",
        "Run Test connection again. Change one thing at a time and test, as you would in production. Then Validate.",
    ),
    resource_group="rg-lab-secure",
    tasks=(
        Task(
            "identity",
            "Go keyless",
            (
                Check(
                    "app-identity",
                    "litware-web has a managed identity",
                    _with_litware(
                        lambda s, account, app: (
                            None
                            if app.properties["identity"] == "SystemAssigned"
                            else "litware-web has no managed identity, so it has nothing to authenticate with except a key."
                        )
                    ),
                    ("Look at the web app's identity setting.",),
                    "A system-assigned managed identity is created and rotated by Azure and lives as long as the app.",
                ),
                Check(
                    "app-keyless",
                    "litware-web authenticates with its identity",
                    _with_litware(
                        lambda s, account, app: (
                            None
                            if app.properties["auth_mode"] == "ManagedIdentity"
                            else "litware-web still sends an API key."
                        )
                    ),
                    ("The app's own setting decides how it authenticates.",),
                    "With a managed identity the app requests Entra ID tokens, so there is no secret to store or leak.",
                ),
                Check(
                    "role",
                    "A least-privilege inference role on litware-ai",
                    _with_litware(_least_privilege),
                    (
                        "Management roles and data roles are different: managing a resource doesn't mean you can call its models.",
                        "Choose the narrowest scope that works: the resource itself.",
                    ),
                    "Cognitive Services OpenAI User allows inference calls but not managing deployments or reading keys, and scoping it to one resource limits the blast radius.",
                ),
                Check(
                    "no-broad-roles",
                    "No owner or contributor roles for the app",
                    _with_litware(_no_broad_roles),
                    ("Remove role assignments the app doesn't need.",),
                    "Broad roles let a compromised app change or delete resources.",
                ),
                Check(
                    "local-auth",
                    "Key-based authentication disabled on litware-ai",
                    _with_litware(
                        lambda s, account, app: (
                            None
                            if account.properties["disable_local_auth"]
                            else "litware-ai still accepts API keys, so a leaked key would still work."
                        )
                    ),
                    ("Keys keep working until the resource refuses them.",),
                    "Disabling local authentication makes Entra ID the only way in, so keys can't be used even if leaked.",
                ),
            ),
        ),
        Task(
            "network",
            "Go private",
            (
                Check(
                    "public-access",
                    "Public network access disabled on litware-ai",
                    _with_litware(
                        lambda s, account, app: (
                            None
                            if account.properties["public_network_access"] == "Disabled"
                            else "litware-ai is still reachable from the internet."
                        )
                    ),
                    ("Look at the resource's networking setting.",),
                    "With public access disabled, only private endpoints can reach the resource.",
                ),
                Check(
                    "private-endpoint",
                    "A private endpoint for litware-ai in the app's network",
                    _with_litware(_private_endpoint),
                    (
                        "Private endpoints are separate resources in the resource group. Put it where the app's traffic goes.",
                    ),
                    "A private endpoint gives the resource a private address inside a virtual network, so traffic never crosses the internet.",
                ),
                Check(
                    "connection-test",
                    "The app still works, without keys",
                    _with_litware(_connection_tested),
                    ("Run Test connection on litware-web and read each step.",),
                    "Testing after each change shows which control broke access, instead of debugging several at once.",
                ),
            ),
        ),
    ),
    completion="You secured an AI endpoint the zero-trust way: a managed identity instead of keys, a least-privilege role on one resource, and private networking, verified end to end.",
    docs=(
        (
            "Role-based access control for Azure OpenAI",
            _LEARN + "ai-services/openai/how-to/role-based-access-control",
        ),
        ("Disable local authentication", _LEARN + "ai-services/disable-local-auth"),
        (
            "Virtual networks and private endpoints",
            _LEARN + "ai-services/cognitive-services-virtual-networks",
        ),
        (
            "Managed identities for App Service",
            _LEARN + "app-service/overview-managed-identity",
        ),
    ),
    approximations=(
        "Virtual networks are names only, and DNS for private endpoints isn't simulated.",
        "Role permissions are reduced to whether a role allows inference with Microsoft Entra ID.",
    ),
    seeds=(
        Seed("resource_group", "rg-lab-secure", None, {"region": "eastus"}),
        Seed("foundry_resource", "litware-ai", "rg-lab-secure", {"region": "eastus"}),
        Seed(
            "web_app",
            "litware-web",
            "rg-lab-secure",
            {
                "region": "eastus",
                "target": "@litware-ai",
                "auth_mode": "ApiKey",
                "vnet_integration": "litware-vnet",
            },
        ),
    ),
)


LABS: dict[str, Lab] = {
    lab.id: lab
    for lab in (
        FOUNDRY_SETUP,
        MODEL_DEPLOYMENT,
        CONTENT_SAFETY,
        SEARCH_INDEX,
        RAG_AGENT,
        DOCUMENT_INTELLIGENCE,
        KEYLESS_SECURITY,
    )
}


def grade(lab: Lab, world: World) -> list[dict[str, Any]]:
    """Run every check against stored state. Deterministic, and never calls a model."""
    state = LabState(world, world.group_named(lab.resource_group))
    results = []
    for task in lab.tasks:
        for check in task.checks:
            feedback = check.test(state)
            results.append(
                {
                    "task_id": task.id,
                    "check_id": check.id,
                    "description": check.description,
                    "passed": feedback is None,
                    "feedback": feedback,
                }
            )
    return results
