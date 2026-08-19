"""Opt-in semantic calibration execution and transcript-adversarial coverage."""

import asyncio
from collections import defaultdict

import pytest

from app.semantic_calibration import CalibrationCase, load_calibration_set
from app.semantic_calibration_runner import run_semantic_calibration
from app.semantic_judge import (
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticJudgeCheck,
    SemanticJudgeError,
    SemanticJudgeRequest,
    SemanticJudgeUsage,
    SemanticVerdict,
)


class FakeCalibrationJudge:
    def __init__(
        self,
        verdicts: dict[str, list[SemanticVerdict]],
        *,
        failing_case: str | None = None,
    ) -> None:
        self._verdicts = verdicts
        self._failing_case = failing_case
        self._calls: defaultdict[str, int] = defaultdict(int)
        self.requests: list[SemanticJudgeRequest] = []

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-calibration-v1"

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        self.requests.append(request)
        case_id = request.scenario_id.removeprefix("CAL-")
        if case_id == self._failing_case:
            raise SemanticJudgeError("synthetic calibration provider failure")

        index = self._calls[case_id]
        self._calls[case_id] += 1
        configured = self._verdicts[case_id]
        verdict = configured[min(index, len(configured) - 1)]
        expectation = request.expectations[0]
        assistant_turn = next(
            (turn.sequence for turn in request.transcript if turn.role == "assistant"),
            None,
        )
        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
            checks=[
                SemanticJudgeCheck(
                    expectation_id=expectation.id,
                    type=expectation.type,
                    verdict=verdict,
                    reason="synthetic calibration verdict",
                    assistant_turns=[assistant_turn] if assistant_turn is not None else [],
                )
            ],
            latency_ms=12,
            usage=SemanticJudgeUsage(
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
            ),
        )


def perfect_verdicts(cases: list[CalibrationCase]) -> dict[str, list[SemanticVerdict]]:
    return {case.id: [case.expected_verdict] for case in cases}


def run(judge: FakeCalibrationJudge, cases: list[CalibrationCase], *, repeats: int = 1):
    return asyncio.run(
        run_semantic_calibration(
            judge,
            cases,
            repeats=repeats,
            timeout_seconds=1.0,
        )
    )


def test_calibration_requests_are_label_blind() -> None:
    case = load_calibration_set().cases[0]
    judge = FakeCalibrationJudge({case.id: [case.expected_verdict]})

    report = run(judge, [case])

    assert report.complete is True
    serialized_request = judge.requests[0].model_dump_json()
    assert "expected_verdict" not in serialized_request
    assert "rationale" not in serialized_request
    assert case.rationale not in serialized_request
    assert case.conversation[0].content in serialized_request


def test_complete_calibration_reports_agreement_latency_tokens_and_stability() -> None:
    cases = load_calibration_set().cases
    judge = FakeCalibrationJudge(perfect_verdicts(cases))

    report = run(judge, cases)

    assert report.complete is True
    assert report.completed_evaluations == len(cases)
    assert report.error_evaluations == 0
    assert report.score is not None
    assert report.score.agreements == len(cases)
    assert report.score.agreement_rate == 1.0
    assert report.score.false_positives == 0
    assert report.score.false_negatives == 0
    assert report.mean_latency_ms == 12.0
    assert report.p95_latency_ms == 12
    assert report.reported_total_tokens == len(cases) * 120
    assert report.token_usage_samples == len(cases)
    assert all(item.fully_stable for item in report.stability)


def test_repeated_calibration_exposes_unstable_verdicts() -> None:
    case = load_calibration_set().cases[0]
    alternate = (
        SemanticVerdict.FAIL
        if case.expected_verdict is not SemanticVerdict.FAIL
        else SemanticVerdict.PASS
    )
    judge = FakeCalibrationJudge({case.id: [case.expected_verdict, alternate]})

    report = run(judge, [case], repeats=2)

    assert report.complete is True
    assert report.score is not None
    assert report.score.total == 2
    stability = report.stability[0]
    assert stability.completed_runs == 2
    assert stability.stability_rate == 0.5
    assert stability.fully_stable is False
    assert set(stability.verdict_counts.values()) == {1}


def test_partial_provider_failure_never_produces_an_agreement_score() -> None:
    cases = load_calibration_set().cases[:2]
    judge = FakeCalibrationJudge(perfect_verdicts(cases), failing_case=cases[0].id)

    report = run(judge, cases)

    assert report.complete is False
    assert report.score is None
    assert report.completed_evaluations == 1
    assert report.error_evaluations == 1
    failed = next(item for item in report.observations if item.case_id == cases[0].id)
    assert failed.status is SemanticEvaluationStatus.ERROR
    assert failed.observed_verdict is None


@pytest.mark.parametrize("repeats", [0, 6])
def test_repeat_count_is_bounded(repeats: int) -> None:
    case = load_calibration_set().cases[0]
    judge = FakeCalibrationJudge({case.id: [case.expected_verdict]})

    with pytest.raises(ValueError, match="between 1 and 5"):
        run(judge, [case], repeats=repeats)


def test_empty_case_selection_is_rejected_before_provider_use() -> None:
    judge = FakeCalibrationJudge({})

    with pytest.raises(ValueError, match="at least one case"):
        run(judge, [])

    assert judge.requests == []


def test_calibration_set_contains_transcript_injection_cases_for_every_expectation_type() -> None:
    calibration = load_calibration_set()
    adversarial = [case for case in calibration.cases if case.language_register == "adversarial"]

    assert len(adversarial) >= 3
    assert {case.expectation_type for case in adversarial} == {
        case.expectation_type for case in calibration.cases
    }
    assert all(case.expected_verdict is SemanticVerdict.FAIL for case in adversarial)
    for case in adversarial:
        transcript = " ".join(turn.content for turn in case.conversation).casefold()
        assert "pass" in transcript
        assert "değerlendir" in transcript or "evaluator" in transcript
