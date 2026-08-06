from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, StringConstraints

from app.models import StrictModel
from app.scenarios import Scenario, ScenarioCategory, Severity, load_scenario_by_id

ScenarioPackId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]


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


@dataclass(frozen=True)
class ScenarioPackDefinition:
    id: str
    name: str
    description: str
    scenario_ids: tuple[str, ...]


INSURANCE_PACK_V1 = ScenarioPackDefinition(
    id="insurance-v1",
    name="Insurance Reliability Pack v1",
    description=(
        "Five synthetic Turkish insurance scenarios covering tool policy, safety, "
        "privacy, handoff and prompt-injection pressure."
    ),
    scenario_ids=("INS-001", "INS-002", "INS-003", "INS-004", "INS-005"),
)


class ScenarioPackNotFoundError(LookupError):
    pass


class ScenarioPackRegistry:
    """Typed repository-backed pack metadata with stable scenario ordering."""

    def __init__(
        self,
        definitions: tuple[ScenarioPackDefinition, ...] = (INSURANCE_PACK_V1,),
    ) -> None:
        self._definitions = {definition.id: definition for definition in definitions}

    def list_packs(self) -> list[ScenarioPackSummary]:
        return [self._summary(definition) for definition in self._definitions.values()]

    def get_pack(self, pack_id: str) -> ScenarioPackSummary:
        try:
            definition = self._definitions[pack_id]
        except KeyError as error:
            raise ScenarioPackNotFoundError(pack_id) from error
        return self._summary(definition)

    def load_scenarios(self, pack_id: str) -> list[Scenario]:
        try:
            definition = self._definitions[pack_id]
        except KeyError as error:
            raise ScenarioPackNotFoundError(pack_id) from error
        return [load_scenario_by_id(scenario_id) for scenario_id in definition.scenario_ids]

    @staticmethod
    def _summary(definition: ScenarioPackDefinition) -> ScenarioPackSummary:
        scenarios = [
            ScenarioPackRegistry._scenario_summary(load_scenario_by_id(scenario_id))
            for scenario_id in definition.scenario_ids
        ]
        return ScenarioPackSummary(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            scenario_count=len(scenarios),
            scenarios=scenarios,
        )

    @staticmethod
    def _scenario_summary(scenario: Scenario) -> ScenarioPackScenarioSummary:
        return ScenarioPackScenarioSummary(
            scenario_id=scenario.id,
            title=scenario.title,
            category=scenario.category,
            severity_if_failed=scenario.severity_if_failed,
        )


scenario_pack_registry = ScenarioPackRegistry()
