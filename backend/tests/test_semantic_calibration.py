"""Calibration fixture validity and deterministic scoring utilities.

No test here contacts a provider: scoring compares human labels against verdicts
supplied by the caller, so calibration remains offline and advisory.
"""

import pytest

from app.semantic_calibration import (
    CALIBRATION_DIRECTORY,
    CalibrationCaseNotFoundError,
    load_calibration_set,
    score_calibration,
)
from app.semantic_judge import SemanticExpectationType, SemanticVerdict


def test_calibration_fixtures_load_and_are_uniquely_identified() -> None:
    calibration = load_calibration_set()

    identifiers = [case.id for case in calibration.cases]
    assert len(identifiers) == len(set(identifiers))
    assert len(calibration.cases) >= 9


def test_every_expectation_type_has_pass_fail_and_uncertain_examples() -> None:
    calibration = load_calibration_set()

    by_type: dict[SemanticExpectationType, set[SemanticVerdict]] = {}
    for case in calibration.cases:
        by_type.setdefault(case.expectation_type, set()).add(case.expected_verdict)

    assert set(by_type) == set(SemanticExpectationType)
    for expectation_type, verdicts in by_type.items():
        assert verdicts == {
            SemanticVerdict.PASS,
            SemanticVerdict.FAIL,
            SemanticVerdict.UNCERTAIN,
        }, f"{expectation_type.value} is missing a labeled verdict class"


def test_calibration_set_covers_multiple_turkish_registers() -> None:
    calibration = load_calibration_set()

    registers = {case.language_register for case in calibration.cases}

    assert {"formal", "colloquial", "noisy"} <= registers


def test_every_case_has_a_reviewable_rationale_and_conversation() -> None:
    calibration = load_calibration_set()

    for case in calibration.cases:
        assert case.rationale.strip(), case.id
        assert case.conversation, case.id
        assert any(turn.role == "assistant" for turn in case.conversation), case.id


def test_calibration_fixtures_live_inside_the_packaged_backend() -> None:
    assert CALIBRATION_DIRECTORY.is_dir()
    assert list(CALIBRATION_DIRECTORY.glob("*.json"))


def test_perfect_agreement_scores_one() -> None:
    calibration = load_calibration_set()
    observed = {case.id: case.expected_verdict for case in calibration.cases}

    score = score_calibration(calibration.cases, observed)

    assert score.total == len(calibration.cases)
    assert score.agreements == score.total
    assert score.agreement_rate == 1.0
    assert score.false_positives == 0
    assert score.false_negatives == 0


def test_false_positive_is_counted_when_judge_invents_a_failure() -> None:
    calibration = load_calibration_set()
    passing = next(
        case for case in calibration.cases if case.expected_verdict is SemanticVerdict.PASS
    )
    observed = {case.id: case.expected_verdict for case in calibration.cases}
    observed[passing.id] = SemanticVerdict.FAIL

    score = score_calibration(calibration.cases, observed)

    assert score.false_positives == 1
    assert score.false_negatives == 0
    assert score.agreements == score.total - 1
    assert score.matrix["pass->fail"] == 1


def test_false_negative_is_counted_when_judge_misses_a_failure() -> None:
    calibration = load_calibration_set()
    failing = next(
        case for case in calibration.cases if case.expected_verdict is SemanticVerdict.FAIL
    )
    observed = {case.id: case.expected_verdict for case in calibration.cases}
    observed[failing.id] = SemanticVerdict.PASS

    score = score_calibration(calibration.cases, observed)

    assert score.false_negatives == 1
    assert score.false_positives == 0
    assert score.matrix["fail->pass"] == 1


def test_uncertain_disagreement_is_neither_false_positive_nor_false_negative() -> None:
    calibration = load_calibration_set()
    passing = next(
        case for case in calibration.cases if case.expected_verdict is SemanticVerdict.PASS
    )
    observed = {case.id: case.expected_verdict for case in calibration.cases}
    observed[passing.id] = SemanticVerdict.UNCERTAIN

    score = score_calibration(calibration.cases, observed)

    assert score.false_positives == 0
    assert score.false_negatives == 0
    assert score.agreements == score.total - 1
    assert score.matrix["pass->uncertain"] == 1


def test_confusion_matrix_totals_match_the_case_count() -> None:
    calibration = load_calibration_set()
    observed = {case.id: SemanticVerdict.UNCERTAIN for case in calibration.cases}

    score = score_calibration(calibration.cases, observed)

    assert sum(score.matrix.values()) == score.total
    assert sum(counts.total for counts in score.by_expectation_type) == score.total


def test_per_expectation_type_breakdown_is_reported() -> None:
    calibration = load_calibration_set()
    observed = {case.id: case.expected_verdict for case in calibration.cases}

    score = score_calibration(calibration.cases, observed)

    reported = {counts.expectation_type for counts in score.by_expectation_type}
    assert reported == set(SemanticExpectationType)
    for counts in score.by_expectation_type:
        assert counts.agreements == counts.total


def test_missing_observed_verdict_is_an_explicit_error_not_a_silent_skip() -> None:
    calibration = load_calibration_set()
    observed = {case.id: case.expected_verdict for case in calibration.cases}
    dropped = calibration.cases[0].id
    del observed[dropped]

    with pytest.raises(CalibrationCaseNotFoundError, match=dropped):
        score_calibration(calibration.cases, observed)


def test_calibration_scoring_never_touches_a_provider() -> None:
    """Scoring is pure: it accepts verdicts, it does not obtain them."""

    import inspect

    from app import semantic_calibration

    source = inspect.getsource(semantic_calibration)
    for forbidden in ("httpx", "OpenAI", "api_key", "requests"):
        assert forbidden not in source
