from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.models import JsonScalar, StrictModel, ToolReference

StableScenarioId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9]{1,15}-[0-9]{3}$"),
]
SemanticVersion = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
SCENARIO_DATA_DIRECTORY = Path(__file__).resolve().parent / "scenario_data"
# Backward-compatible alias used by existing insurance fixture tests.
SCENARIO_DIRECTORY = SCENARIO_DATA_DIRECTORY / "insurance"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScenarioCategory(StrEnum):
    TOOL_CALL_POLICY = "tool_call_policy"
    COVERAGE_SAFETY = "coverage_safety"
    PRIVACY = "privacy"
    HUMAN_HANDOFF = "human_handoff"
    PROMPT_INJECTION = "prompt_injection"
    CONTEXT_RETENTION = "context_retention"
    AMBIGUOUS_INTENT = "ambiguous_intent"
    TURKISH_NOISE = "turkish_noise"
    REPEATED_REQUEST = "repeated_request"
    FAILED_TOOL_RECOVERY = "failed_tool_recovery"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Persona(StrictModel):
    name: str
    language: Literal["tr-TR"]
    tone: str
    technical_level: Literal["low", "medium", "high"] = "medium"
    language_style: Literal["formal", "casual"] = "casual"
    typo_level: Literal["none", "low", "medium", "high"] = "none"


class SyntheticContext(StrictModel):
    policy_id: str | None = None
    vehicle: str | None = None
    damage: str | None = None
    required_document: str | None = None
    document_available: bool | None = None
    request_context: str | None = None
    # Domain-specific fixture data for future packs. Existing insurance fields
    # stay first-class and backwards compatible while new verticals avoid model churn.
    attributes: dict[str, JsonScalar] = Field(default_factory=dict)


class ExpectedToolCall(StrictModel):
    name: ToolReference
    required: bool = True
    constraints: dict[str, JsonScalar] = Field(default_factory=dict)


class ForbiddenToolCall(StrictModel):
    name: ToolReference
    condition: str


class ExpectedBrokenResult(StrictModel):
    status: Literal["fail"]
    category: str
    severity: Severity
    reason: str


class Scenario(StrictModel):
    id: StableScenarioId
    version: SemanticVersion
    title: str
    category: ScenarioCategory
    severity_if_failed: Severity
    persona: Persona
    initial_user_goal: str
    max_turns: int = Field(ge=1, le=50)
    synthetic_context: SyntheticContext
    scripted_user_turns: list[str] = Field(min_length=1)
    expected_outcomes: list[str] = Field(min_length=1)
    expected_tool_calls: list[ExpectedToolCall]
    forbidden_tool_calls: list[ForbiddenToolCall] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(min_length=1)
    deterministic_checks: list[str] = Field(min_length=1)
    expected_healthy_result: Literal["pass"]
    expected_broken_result: ExpectedBrokenResult | None = None

    difficulty: Difficulty = Difficulty.MEDIUM
    tags: list[str] = Field(default_factory=list)
    hidden_context: str | None = None
    expected_behaviors: list[str] = Field(default_factory=list)
    forbidden_response_phrases: list[str] = Field(default_factory=list)
    required_response_phrases: list[str] = Field(default_factory=list)
    max_tool_call_counts: dict[ToolReference, int] = Field(default_factory=dict)
    loop_detection_enabled: bool = False


def load_scenario(path: Path) -> Scenario:
    """Load one packaged fixture and fail closed on malformed JSON/schema."""

    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


class ScenarioNotFoundError(LookupError):
    pass


def load_scenario_by_id(scenario_id: str) -> Scenario:
    """Resolve a fixture by validated content instead of interpolating a user path.

    Scenario files are discovered one vertical directory below ``scenario_data``
    so adding a future ``ecommerce`` or ``banking`` pack requires no loader change.
    """

    for path in sorted(SCENARIO_DATA_DIRECTORY.glob("*/*.json")):
        scenario = load_scenario(path)
        if scenario.id == scenario_id:
            return scenario
    raise ScenarioNotFoundError(scenario_id)
