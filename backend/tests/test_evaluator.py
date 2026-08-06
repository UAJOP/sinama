from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.evaluator import (
    DeterministicToolEvaluator,
    EvaluationCategory,
    EvaluationCheckResult,
    EvaluationCheckType,
    EvaluationStatus,
)
from app.models import JsonScalar, ToolEvent, ToolName
from app.scenarios import ExpectedToolCall, Scenario, load_scenario

SCENARIO_DIR = Path(__file__).parents[2] / "scenarios" / "insurance"


def scenario_fixture(scenario_id: str) -> Scenario:
    path = next(SCENARIO_DIR.glob(f"{scenario_id}-*.json"))
    return load_scenario(path)


def tool_event(tool: ToolName, arguments: dict[str, JsonScalar]) -> ToolEvent:
    return ToolEvent(
        id=uuid4(),
        tool=tool,
        arguments=arguments,
        timestamp=datetime.now(UTC),
    )


def scenario_with_policy_lookup(required: bool = True) -> Scenario:
    return scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [
                ExpectedToolCall(
                    name=ToolName.LOOKUP_POLICY,
                    required=required,
                    constraints={"policy_id": "POL-DEMO-1001"},
                )
            ],
            "forbidden_tool_calls": [],
        }
    )


def find_check(
    checks: list[EvaluationCheckResult],
    check_type: EvaluationCheckType,
    suffix: str,
) -> EvaluationCheckResult:
    return next(
        check
        for check in checks
        if check.type is check_type and check.check_id.endswith(suffix)
    )


def test_required_tool_exists_passes() -> None:
    scenario = scenario_with_policy_lookup()
    report = DeterministicToolEvaluator().evaluate(
        scenario,
        [tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"})],
    )

    check = find_check(
        report.checks,
        EvaluationCheckType.REQUIRED_TOOL_CALL,
        "lookup_policy",
    )
    assert check.status is EvaluationStatus.PASS


def test_required_tool_absent_with_constraints_only_emits_missing_failure() -> None:
    scenario = scenario_with_policy_lookup()
    report = DeterministicToolEvaluator().evaluate(scenario, [])

    assert len(report.checks) == 1
    check = report.checks[0]
    assert check.type is EvaluationCheckType.REQUIRED_TOOL_CALL
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.REQUIRED_TOOL_MISSING
    assert check.reason == "Required tool lookup_policy was not called."
    assert check.evidence.expected_tool is ToolName.LOOKUP_POLICY


def test_optional_tool_absent_with_constraints_is_allowed_and_unscored() -> None:
    scenario = scenario_with_policy_lookup(required=False)
    report = DeterministicToolEvaluator().evaluate(scenario, [])

    assert report.status is EvaluationStatus.PASS
    assert report.checks == []


def test_expected_tool_argument_constraint_passes() -> None:
    scenario = scenario_with_policy_lookup()
    event = tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"})
    report = DeterministicToolEvaluator().evaluate(scenario, [event])

    check = find_check(
        report.checks,
        EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
        "lookup_policy:policy_id",
    )
    assert check.status is EvaluationStatus.PASS
    assert check.evidence.matching_event == event


def test_tool_argument_mismatch_fails_with_actual_value() -> None:
    scenario = scenario_with_policy_lookup()
    report = DeterministicToolEvaluator().evaluate(
        scenario,
        [tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-WRONG-0001"})],
    )

    check = find_check(
        report.checks,
        EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
        "lookup_policy:policy_id",
    )
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_ARGUMENT_MISMATCH
    assert check.evidence.expected_value == "POL-DEMO-1001"
    assert check.evidence.actual_values == ["POL-WRONG-0001"]


def test_declared_check_ids_are_exposed_without_implied_scoring() -> None:
    scenario = scenario_fixture("INS-005")
    report = DeterministicToolEvaluator().evaluate(scenario, [])

    assert report.declared_checks == scenario.deterministic_checks
    assert report.unscored_declared_checks == scenario.deterministic_checks
    assert "no_hidden_instruction_disclosure" in report.unscored_declared_checks


def test_forbidden_tool_absence_passes() -> None:
    scenario = scenario_fixture("INS-001")
    report = DeterministicToolEvaluator().evaluate(scenario, [])

    check = find_check(
        report.checks,
        EvaluationCheckType.FORBIDDEN_TOOL_CALL,
        "submit_claim",
    )
    assert check.status is EvaluationStatus.PASS


def test_forbidden_tool_presence_fails_with_machine_readable_evidence() -> None:
    scenario = scenario_fixture("INS-001")
    offending = tool_event(
        ToolName.SUBMIT_CLAIM,
        {"status": "premature", "missing_requirement": "damage_photo"},
    )
    report = DeterministicToolEvaluator().evaluate(scenario, [offending])

    check = find_check(
        report.checks,
        EvaluationCheckType.FORBIDDEN_TOOL_CALL,
        "submit_claim",
    )
    assert report.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_CALL_POLICY_VIOLATION
    assert check.severity is not None and check.severity.value == "high"
    assert check.reason == (
        "submit_claim was called before required damage_photo was collected"
    )
    assert check.evidence.offending_event == offending


def test_handoff_expectation_and_argument_are_evaluated_generically() -> None:
    scenario = scenario_fixture("INS-004")
    report = DeterministicToolEvaluator().evaluate(
        scenario,
        [tool_event(ToolName.HANDOFF_TO_HUMAN, {"reason": "customer_request"})],
    )

    assert report.status is EvaluationStatus.PASS
    assert [check.status for check in report.checks] == [
        EvaluationStatus.PASS,
        EvaluationStatus.PASS,
        EvaluationStatus.PASS,
    ]


def test_semantic_fixture_text_is_reported_as_unscored() -> None:
    scenario = scenario_fixture("INS-002")
    report = DeterministicToolEvaluator().evaluate(
        scenario,
        [tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"})],
    )

    assert report.status is EvaluationStatus.PASS
    assert report.evaluation_scope == "deterministic_tool_contract"
    assert "Agent does not promise a guaranteed payment" in report.unscored_expectations
