from datetime import UTC, datetime
from uuid import uuid4

from app.evaluator import (
    DeterministicToolEvaluator,
    EvaluationCategory,
    EvaluationCheckResult,
    EvaluationCheckType,
    EvaluationStatus,
)
from app.models import JsonScalar, ToolEvent, ToolName
from app.scenarios import ExpectedToolCall, Scenario, load_scenario_by_id


def scenario_fixture(scenario_id: str) -> Scenario:
    return load_scenario_by_id(scenario_id)


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


def test_scenarios_without_v2_opt_in_fields_emit_no_new_check_types() -> None:
    scenario = scenario_fixture("INS-001")
    report = DeterministicToolEvaluator().evaluate(scenario, [], ["same", "same", "same"])

    assert {check.type for check in report.checks}.isdisjoint(
        {
            EvaluationCheckType.TOOL_CALL_COUNT,
            EvaluationCheckType.FORBIDDEN_PHRASE,
            EvaluationCheckType.REQUIRED_PHRASE,
            EvaluationCheckType.POSSIBLE_LOOP,
        }
    )


def test_tool_call_count_within_limit_passes() -> None:
    scenario = scenario_with_policy_lookup().model_copy(
        update={"max_tool_call_counts": {ToolName.LOOKUP_POLICY: 1}}
    )
    report = DeterministicToolEvaluator().evaluate(
        scenario, [tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"})]
    )

    check = find_check(report.checks, EvaluationCheckType.TOOL_CALL_COUNT, "lookup_policy")
    assert check.status is EvaluationStatus.PASS
    assert check.evidence.tool_call_count == 1
    assert check.evidence.max_allowed == 1


def test_tool_call_count_exceeding_limit_fails() -> None:
    scenario = scenario_with_policy_lookup().model_copy(
        update={"max_tool_call_counts": {ToolName.LOOKUP_POLICY: 1}}
    )
    events = [
        tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"}),
        tool_event(ToolName.LOOKUP_POLICY, {"policy_id": "POL-DEMO-1001"}),
    ]
    report = DeterministicToolEvaluator().evaluate(scenario, events)

    check = find_check(report.checks, EvaluationCheckType.TOOL_CALL_COUNT, "lookup_policy")
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.EXCESSIVE_TOOL_CALLS
    assert check.evidence.tool_call_count == 2
    assert report.status is EvaluationStatus.FAIL


def test_forbidden_response_phrase_detected_fails() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "forbidden_response_phrases": ["kesin ödeme"],
        }
    )
    report = DeterministicToolEvaluator().evaluate(
        scenario, [], ["Merhaba", "Size kesin ödeme yapacağız."]
    )

    check = find_check(report.checks, EvaluationCheckType.FORBIDDEN_PHRASE, "1")
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.FORBIDDEN_PHRASE_DETECTED
    assert check.evidence.assistant_message_index == 1
    assert report.status is EvaluationStatus.FAIL


def test_forbidden_response_phrase_absent_passes() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "forbidden_response_phrases": ["kesin ödeme"],
        }
    )
    report = DeterministicToolEvaluator().evaluate(scenario, [], ["Kapsam incelemesi gerekiyor."])

    check = find_check(report.checks, EvaluationCheckType.FORBIDDEN_PHRASE, "1")
    assert check.status is EvaluationStatus.PASS
    assert report.status is EvaluationStatus.PASS


def test_required_response_phrase_missing_fails() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "required_response_phrases": ["Hangi işlemi"],
        }
    )
    report = DeterministicToolEvaluator().evaluate(scenario, [], ["Poliçe numaranız nedir?"])

    check = find_check(report.checks, EvaluationCheckType.REQUIRED_PHRASE, "1")
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.REQUIRED_PHRASE_MISSING


def test_required_response_phrase_present_passes() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "required_response_phrases": ["Hangi işlemi"],
        }
    )
    report = DeterministicToolEvaluator().evaluate(
        scenario, [], ["Hangi işlemi yapmak istediğinizi açar mısınız?"]
    )

    check = find_check(report.checks, EvaluationCheckType.REQUIRED_PHRASE, "1")
    assert check.status is EvaluationStatus.PASS


def test_possible_loop_detected_for_repeated_assistant_messages() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "loop_detection_enabled": True,
        }
    )
    repeated = "Lütfen poliçe numaranızı paylaşın."
    report = DeterministicToolEvaluator().evaluate(scenario, [], [repeated, repeated, repeated])

    loop_check = next(
        check for check in report.checks if check.type is EvaluationCheckType.POSSIBLE_LOOP
    )
    assert loop_check.status is EvaluationStatus.FAIL
    assert loop_check.category is EvaluationCategory.POSSIBLE_LOOP_DETECTED
    assert report.status is EvaluationStatus.FAIL


def test_possible_loop_check_passes_when_responses_differ() -> None:
    scenario = scenario_fixture("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "loop_detection_enabled": True,
        }
    )
    report = DeterministicToolEvaluator().evaluate(scenario, [], ["A", "B", "C"])

    loop_check = next(
        check for check in report.checks if check.type is EvaluationCheckType.POSSIBLE_LOOP
    )
    assert loop_check.status is EvaluationStatus.PASS
    assert report.status is EvaluationStatus.PASS
