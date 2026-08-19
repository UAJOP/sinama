from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.evaluator import (
    DeterministicToolEvaluator,
    EvaluationCategory,
    EvaluationCheckType,
    EvaluationStatus,
)
from app.failures import build_failures
from app.models import JsonScalar, ToolEvent, ToolName, ToolReference
from app.scenarios import (
    ArgumentExistsConstraint,
    ArgumentOneOfConstraint,
    ArgumentPatternConstraint,
    ArgumentRangeConstraint,
    Scenario,
    ToolOrderConstraint,
    load_scenario_by_id,
)


def scenario_fixture() -> Scenario:
    return load_scenario_by_id("INS-001").model_copy(
        update={
            "expected_tool_calls": [],
            "forbidden_tool_calls": [],
            "max_tool_call_counts": {},
            "forbidden_response_phrases": [],
            "required_response_phrases": [],
            "loop_detection_enabled": False,
            "tool_order_constraints": [],
            "argument_constraints": [],
        }
    )


def event(tool: ToolReference, arguments: dict[str, JsonScalar] | None = None) -> ToolEvent:
    return ToolEvent(
        id=uuid4(),
        tool=tool,
        arguments=arguments or {},
        timestamp=datetime.now(UTC),
    )


def only_check(report_type: EvaluationCheckType, scenario: Scenario, trace: list[ToolEvent]):
    report = DeterministicToolEvaluator().evaluate(scenario, trace)
    matches = [check for check in report.checks if check.type is report_type]
    assert len(matches) == 1
    return report, matches[0]


def test_tool_precondition_passes_when_prerequisite_occurs_first() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "tool_order_constraints": [
                ToolOrderConstraint(
                    before=ToolName.LOOKUP_POLICY,
                    after=ToolName.SUBMIT_CLAIM,
                )
            ]
        }
    )
    prerequisite = event(ToolName.LOOKUP_POLICY)
    submit = event(ToolName.SUBMIT_CLAIM)

    report, check = only_check(
        EvaluationCheckType.TOOL_PRECONDITION,
        scenario,
        [prerequisite, submit],
    )

    assert report.status is EvaluationStatus.PASS
    assert check.status is EvaluationStatus.PASS
    assert check.evidence.prerequisite_tool is ToolName.LOOKUP_POLICY
    assert check.evidence.matching_event == prerequisite


def test_tool_precondition_fails_on_first_premature_after_event() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "tool_order_constraints": [
                ToolOrderConstraint(
                    before=ToolName.LOOKUP_POLICY,
                    after=ToolName.SUBMIT_CLAIM,
                )
            ]
        }
    )
    premature = event(ToolName.SUBMIT_CLAIM)
    later_lookup = event(ToolName.LOOKUP_POLICY)

    report, check = only_check(
        EvaluationCheckType.TOOL_PRECONDITION,
        scenario,
        [premature, later_lookup],
    )

    assert report.status is EvaluationStatus.FAIL
    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_PRECONDITION_VIOLATION
    assert check.evidence.offending_event == premature

    failures = build_failures(report.checks, {premature.id: 2})
    assert failures[0].turn == 2
    assert failures[0].type is EvaluationCheckType.TOOL_PRECONDITION
    assert "lookup_policy" in failures[0].expected


def test_tool_precondition_is_satisfied_when_after_tool_is_never_called() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "tool_order_constraints": [
                ToolOrderConstraint(
                    before=ToolName.LOOKUP_POLICY,
                    after=ToolName.SUBMIT_CLAIM,
                )
            ]
        }
    )

    report, check = only_check(EvaluationCheckType.TOOL_PRECONDITION, scenario, [])

    assert report.status is EvaluationStatus.PASS
    assert check.status is EvaluationStatus.PASS
    assert check.evidence.offending_event is None


def test_argument_exists_checks_every_observed_tool_call() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentExistsConstraint(
                    type="exists",
                    tool="refund_order",
                    argument="order_id",
                )
            ]
        }
    )
    good = event("refund_order", {"order_id": "ORD-1"})
    bad = event("refund_order", {"reason": "customer_request"})

    report, check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
        scenario,
        [good, bad],
    )

    assert check.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_ARGUMENT_MISSING
    assert check.evidence.offending_event == bad
    failure = build_failures(report.checks, {bad.id: 4})[0]
    assert failure.turn == 4
    assert "order_id" in failure.title


def test_argument_exists_accepts_present_null_value() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentExistsConstraint(
                    type="exists",
                    tool="collect_claim_details",
                    argument="optional_note",
                )
            ]
        }
    )

    report, check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
        scenario,
        [event("collect_claim_details", {"optional_note": None})],
    )

    assert report.status is EvaluationStatus.PASS
    assert check.status is EvaluationStatus.PASS


def test_one_of_constraint_accepts_allowed_value_and_rejects_other_value() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentOneOfConstraint(
                    type="one_of",
                    tool="refund_order",
                    argument="reason",
                    values=["damaged", "wrong_item"],
                )
            ]
        }
    )

    passed, pass_check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
        scenario,
        [event("refund_order", {"reason": "damaged"})],
    )
    failed, fail_check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
        scenario,
        [event("refund_order", {"reason": "changed_mind"})],
    )

    assert passed.status is EvaluationStatus.PASS
    assert pass_check.status is EvaluationStatus.PASS
    assert failed.status is EvaluationStatus.FAIL
    assert fail_check.category is EvaluationCategory.TOOL_ARGUMENT_NOT_ALLOWED
    assert fail_check.evidence.allowed_values == ["damaged", "wrong_item"]
    assert build_failures(failed.checks, {})[0].type is EvaluationCheckType.TOOL_ARGUMENT_ONE_OF


def test_one_of_treats_json_boolean_as_distinct_from_number() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentOneOfConstraint(
                    type="one_of",
                    tool="set_priority",
                    argument="priority",
                    values=[1],
                )
            ]
        }
    )

    report, check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
        scenario,
        [event("set_priority", {"priority": True})],
    )

    assert report.status is EvaluationStatus.FAIL
    assert check.status is EvaluationStatus.FAIL


def test_pattern_constraint_uses_full_match() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentPatternConstraint(
                    type="pattern",
                    tool="lookup_order",
                    argument="order_id",
                    pattern=r"ORD-[0-9]{4}",
                )
            ]
        }
    )

    passed, _ = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
        scenario,
        [event("lookup_order", {"order_id": "ORD-1024"})],
    )
    failed, check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
        scenario,
        [event("lookup_order", {"order_id": "prefix-ORD-1024"})],
    )

    assert passed.status is EvaluationStatus.PASS
    assert failed.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_ARGUMENT_PATTERN_MISMATCH
    assert check.evidence.pattern == r"ORD-[0-9]{4}"
    assert build_failures(failed.checks, {})[0].type is EvaluationCheckType.TOOL_ARGUMENT_PATTERN


def test_range_constraint_includes_minimum_and_maximum_boundaries() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentRangeConstraint(
                    type="range",
                    tool="set_refund_amount",
                    argument="amount",
                    min_value=0,
                    max_value=1000,
                )
            ]
        }
    )

    minimum, _ = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
        scenario,
        [event("set_refund_amount", {"amount": 0})],
    )
    maximum, _ = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
        scenario,
        [event("set_refund_amount", {"amount": 1000})],
    )
    outside, check = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
        scenario,
        [event("set_refund_amount", {"amount": 1000.01})],
    )

    assert minimum.status is EvaluationStatus.PASS
    assert maximum.status is EvaluationStatus.PASS
    assert outside.status is EvaluationStatus.FAIL
    assert check.category is EvaluationCategory.TOOL_ARGUMENT_RANGE_VIOLATION
    assert check.evidence.min_value == 0
    assert check.evidence.max_value == 1000
    assert build_failures(outside.checks, {})[0].type is EvaluationCheckType.TOOL_ARGUMENT_RANGE


def test_range_constraint_rejects_boolean_and_non_numeric_values() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentRangeConstraint(
                    type="range",
                    tool="set_refund_amount",
                    argument="amount",
                    min_value=0,
                )
            ]
        }
    )

    boolean_report, _ = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
        scenario,
        [event("set_refund_amount", {"amount": True})],
    )
    string_report, _ = only_check(
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
        scenario,
        [event("set_refund_amount", {"amount": "100"})],
    )

    assert boolean_report.status is EvaluationStatus.FAIL
    assert string_report.status is EvaluationStatus.FAIL


def test_rich_argument_rule_is_not_scored_when_optional_tool_is_absent() -> None:
    scenario = scenario_fixture().model_copy(
        update={
            "argument_constraints": [
                ArgumentExistsConstraint(type="exists", tool="refund_order", argument="order_id")
            ]
        }
    )

    report = DeterministicToolEvaluator().evaluate(scenario, [])

    assert report.status is EvaluationStatus.PASS
    assert not any(
        check.type is EvaluationCheckType.TOOL_ARGUMENT_EXISTS for check in report.checks
    )


def test_existing_insurance_fixture_emits_no_rich_constraint_checks() -> None:
    scenario = load_scenario_by_id("INS-001")
    report = DeterministicToolEvaluator().evaluate(scenario, [])
    rich_types = {
        EvaluationCheckType.TOOL_PRECONDITION,
        EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
        EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
        EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
        EvaluationCheckType.TOOL_ARGUMENT_RANGE,
    }

    assert scenario.tool_order_constraints == []
    assert scenario.argument_constraints == []
    assert {check.type for check in report.checks}.isdisjoint(rich_types)


def test_malformed_rich_constraint_definitions_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ToolOrderConstraint(before="lookup_order", after="lookup_order")

    with pytest.raises(ValidationError):
        ArgumentOneOfConstraint(type="one_of", tool="refund_order", argument="reason", values=[])

    with pytest.raises(ValidationError):
        ArgumentPatternConstraint(
            type="pattern",
            tool="lookup_order",
            argument="order_id",
            pattern="[",
        )

    with pytest.raises(ValidationError):
        ArgumentRangeConstraint(type="range", tool="refund_order", argument="amount")

    with pytest.raises(ValidationError):
        ArgumentRangeConstraint(
            type="range",
            tool="refund_order",
            argument="amount",
            min_value=100,
            max_value=10,
        )
