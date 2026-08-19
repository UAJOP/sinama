from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.models import AgentTarget, StrictModel
from app.scenarios import Scenario, ScenarioCategory, Severity, load_scenario_by_id

ScenarioPackId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
ScenarioSuiteId = ScenarioPackId


class ScenarioPackScenarioSummary(StrictModel):
    scenario_id: str
    title: str
    category: ScenarioCategory
    severity_if_failed: Severity


class ScenarioPackSummary(StrictModel):
    id: ScenarioPackId
    name: str
    description: str
    scenario_count: int = Field(ge=1)
    scenarios: list[ScenarioPackScenarioSummary]
    # Additive defaults preserve validation of historical persisted snapshots.
    kind: Literal["pack", "suite"] = "pack"
    included_pack_ids: list[ScenarioPackId] = Field(default_factory=list)
    allowed_agent_targets: list[AgentTarget] = Field(
        default_factory=lambda: [AgentTarget.BUILT_IN_DEMO, AgentTarget.EXTERNAL_HTTP]
    )


class TestSuiteSummary(StrictModel):
    id: ScenarioSuiteId
    name: str
    description: str
    pack_ids: list[ScenarioPackId] = Field(min_length=1)
    scenario_count: int = Field(ge=1)
    scenarios: list[ScenarioPackScenarioSummary]
    allowed_agent_targets: list[AgentTarget] = Field(min_length=1)


@dataclass(frozen=True)
class ScenarioPackDefinition:
    id: str
    name: str
    description: str
    scenario_ids: tuple[str, ...]
    allowed_agent_targets: tuple[AgentTarget, ...] = (
        AgentTarget.BUILT_IN_DEMO,
        AgentTarget.EXTERNAL_HTTP,
    )


@dataclass(frozen=True)
class TestSuiteDefinition:
    id: str
    name: str
    description: str
    pack_ids: tuple[str, ...]


INSURANCE_PACK_V1 = ScenarioPackDefinition(
    id="insurance-v1",
    name="Insurance Reliability Pack v1",
    description=(
        "Ten synthetic Turkish insurance scenarios covering tool policy, safety, "
        "privacy, handoff, prompt-injection pressure, context retention, ambiguous "
        "intent, Turkish typo/noise robustness, repeated requests and failed-tool "
        "recovery."
    ),
    scenario_ids=(
        "INS-001",
        "INS-002",
        "INS-003",
        "INS-004",
        "INS-005",
        "INS-006",
        "INS-007",
        "INS-008",
        "INS-009",
        "INS-010",
    ),
)


ECOMMERCE_PACK_V1 = ScenarioPackDefinition(
    id="ecommerce-v1",
    name="E-commerce Reliability Pack v1",
    description=(
        "Four hand-reviewed Turkish e-commerce scenarios covering refund ordering, "
        "failed order lookup recovery, escalation and duplicate-refund prevention."
    ),
    scenario_ids=("ECOM-001", "ECOM-002", "ECOM-003", "ECOM-004"),
    # The built-in demo models insurance only. E-commerce is intentionally an
    # external-agent proof vertical instead of hiding domain switching in core code.
    allowed_agent_targets=(AgentTarget.EXTERNAL_HTTP,),
)


CUSTOMER_SERVICE_CORE_V1 = TestSuiteDefinition(
    id="customer-service-core-v1",
    name="Customer Service Core Suite v1",
    description=(
        "Cross-vertical suite composing the insurance and e-commerce reliability packs "
        "for agents that intentionally support both workflows."
    ),
    pack_ids=("insurance-v1", "ecommerce-v1"),
)


class ScenarioPackNotFoundError(LookupError):
    pass


class TestSuiteNotFoundError(LookupError):
    pass


class ScenarioCollectionNotFoundError(LookupError):
    pass


class ScenarioPackRegistry:
    """Typed packaged scenario metadata with stable pack and suite ordering."""

    def __init__(
        self,
        definitions: tuple[ScenarioPackDefinition, ...] = (
            INSURANCE_PACK_V1,
            ECOMMERCE_PACK_V1,
        ),
        suite_definitions: tuple[TestSuiteDefinition, ...] = (CUSTOMER_SERVICE_CORE_V1,),
    ) -> None:
        self._definitions = {definition.id: definition for definition in definitions}
        self._suite_definitions = {
            definition.id: definition for definition in suite_definitions
        }

        unknown_pack_ids = {
            pack_id
            for suite in suite_definitions
            for pack_id in suite.pack_ids
            if pack_id not in self._definitions
        }
        if unknown_pack_ids:
            unknown = ", ".join(sorted(unknown_pack_ids))
            raise ValueError(f"Test suite references unknown scenario pack(s): {unknown}")

    def list_packs(self) -> list[ScenarioPackSummary]:
        return [self._pack_summary(definition) for definition in self._definitions.values()]

    def list_suites(self) -> list[TestSuiteSummary]:
        return [self._suite_summary(definition) for definition in self._suite_definitions.values()]

    def get_pack(self, pack_id: str) -> ScenarioPackSummary:
        try:
            definition = self._definitions[pack_id]
        except KeyError as error:
            raise ScenarioPackNotFoundError(pack_id) from error
        return self._pack_summary(definition)

    def get_suite(self, suite_id: str) -> TestSuiteSummary:
        try:
            definition = self._suite_definitions[suite_id]
        except KeyError as error:
            raise TestSuiteNotFoundError(suite_id) from error
        return self._suite_summary(definition)

    def get_collection(self, collection_id: str) -> ScenarioPackSummary:
        if collection_id in self._definitions:
            return self._pack_summary(self._definitions[collection_id])
        if collection_id in self._suite_definitions:
            return self._suite_execution_summary(self._suite_definitions[collection_id])
        raise ScenarioCollectionNotFoundError(collection_id)

    def load_scenarios(self, pack_id: str) -> list[Scenario]:
        try:
            definition = self._definitions[pack_id]
        except KeyError as error:
            raise ScenarioPackNotFoundError(pack_id) from error
        return self._load_pack_scenarios(definition)

    def load_collection_scenarios(self, collection_id: str) -> list[Scenario]:
        if collection_id in self._definitions:
            return self._load_pack_scenarios(self._definitions[collection_id])
        if collection_id in self._suite_definitions:
            suite = self._suite_definitions[collection_id]
            return [
                scenario
                for pack_id in suite.pack_ids
                for scenario in self._load_pack_scenarios(self._definitions[pack_id])
            ]
        raise ScenarioCollectionNotFoundError(collection_id)

    @staticmethod
    def _load_pack_scenarios(definition: ScenarioPackDefinition) -> list[Scenario]:
        return [load_scenario_by_id(scenario_id) for scenario_id in definition.scenario_ids]

    @staticmethod
    def _scenario_summary(scenario: Scenario) -> ScenarioPackScenarioSummary:
        return ScenarioPackScenarioSummary(
            scenario_id=scenario.id,
            title=scenario.title,
            category=scenario.category,
            severity_if_failed=scenario.severity_if_failed,
        )

    def _pack_summary(self, definition: ScenarioPackDefinition) -> ScenarioPackSummary:
        scenarios = [
            self._scenario_summary(load_scenario_by_id(scenario_id))
            for scenario_id in definition.scenario_ids
        ]
        return ScenarioPackSummary(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            scenario_count=len(scenarios),
            scenarios=scenarios,
            allowed_agent_targets=list(definition.allowed_agent_targets),
        )

    def _suite_summary(self, definition: TestSuiteDefinition) -> TestSuiteSummary:
        execution_summary = self._suite_execution_summary(definition)
        return TestSuiteSummary(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            pack_ids=list(definition.pack_ids),
            scenario_count=execution_summary.scenario_count,
            scenarios=execution_summary.scenarios,
            allowed_agent_targets=execution_summary.allowed_agent_targets,
        )

    def _suite_execution_summary(
        self, definition: TestSuiteDefinition
    ) -> ScenarioPackSummary:
        pack_definitions = [self._definitions[pack_id] for pack_id in definition.pack_ids]
        scenarios = [
            self._scenario_summary(load_scenario_by_id(scenario_id))
            for pack in pack_definitions
            for scenario_id in pack.scenario_ids
        ]
        allowed_targets = set(pack_definitions[0].allowed_agent_targets)
        for pack in pack_definitions[1:]:
            allowed_targets.intersection_update(pack.allowed_agent_targets)
        if not allowed_targets:
            raise ValueError(
                f"Test suite {definition.id} has no agent target supported by every included pack."
            )
        return ScenarioPackSummary(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            scenario_count=len(scenarios),
            scenarios=scenarios,
            kind="suite",
            included_pack_ids=list(definition.pack_ids),
            allowed_agent_targets=[
                target
                for target in (AgentTarget.BUILT_IN_DEMO, AgentTarget.EXTERNAL_HTTP)
                if target in allowed_targets
            ],
        )


scenario_pack_registry = ScenarioPackRegistry()
