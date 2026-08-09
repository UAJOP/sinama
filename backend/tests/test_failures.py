from datetime import UTC, datetime
from uuid import uuid4

from app.evaluator import (
    EvaluationCategory,
    EvaluationCheckResult,
    EvaluationCheckType,
    EvaluationEvidence,
    EvaluationStatus,
)
from app.failures import build_failures
from app.models import ToolEvent, ToolName
from app.scenarios import Severity


def tool_event(tool: ToolName = ToolName.SUBMIT_CLAIM) -> ToolEvent:
    return ToolEvent(id=uuid4(), tool=tool, arguments={}, timestamp=datetime.now(UTC))


def test_build_failures_skips_passing_checks() -> None:
    checks = [
        EvaluationCheckResult(
            check_id="a",
            type=EvaluationCheckType.REQUIRED_TOOL_CALL,
            status=EvaluationStatus.PASS,
            reason="ok",
            evidence=EvaluationEvidence(),
        )
    ]

    assert build_failures(checks, {}) == []


def test_build_failures_resolves_turn_from_offending_event() -> None:
    event = tool_event()
    checks = [
        EvaluationCheckResult(
            check_id="forbidden_tool:1:submit_claim",
            type=EvaluationCheckType.FORBIDDEN_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_CALL_POLICY_VIOLATION,
            severity=Severity.HIGH,
            reason="submit_claim was called too early",
            evidence=EvaluationEvidence(
                expected_tool=ToolName.SUBMIT_CLAIM, offending_event=event
            ),
        )
    ]

    failures = build_failures(checks, {event.id: 3})

    assert len(failures) == 1
    assert failures[0].turn == 3
    assert failures[0].severity is Severity.HIGH
    assert failures[0].description == "submit_claim was called too early"
    assert "submit_claim" in failures[0].title


def test_build_failures_resolves_turn_from_assistant_message_index() -> None:
    checks = [
        EvaluationCheckResult(
            check_id="required_phrase:1",
            type=EvaluationCheckType.REQUIRED_PHRASE,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.REQUIRED_PHRASE_MISSING,
            severity=Severity.MEDIUM,
            reason="missing phrase",
            evidence=EvaluationEvidence(assistant_message_index=2),
        )
    ]

    failures = build_failures(checks, {})

    assert failures[0].turn == 3


def test_build_failures_turn_is_none_when_unresolvable() -> None:
    checks = [
        EvaluationCheckResult(
            check_id="required_tool:1:lookup_policy",
            type=EvaluationCheckType.REQUIRED_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.REQUIRED_TOOL_MISSING,
            severity=Severity.HIGH,
            reason="not called",
            evidence=EvaluationEvidence(expected_tool=ToolName.LOOKUP_POLICY),
        )
    ]

    failures = build_failures(checks, {})

    assert failures[0].turn is None


def test_build_failures_defaults_severity_when_absent() -> None:
    checks = [
        EvaluationCheckResult(
            check_id="possible_loop",
            type=EvaluationCheckType.POSSIBLE_LOOP,
            status=EvaluationStatus.FAIL,
            reason="loop",
            evidence=EvaluationEvidence(),
        )
    ]

    failures = build_failures(checks, {})

    assert failures[0].severity is Severity.MEDIUM
