"""Hand-labeled semantic calibration fixtures and deterministic agreement metrics.

These fixtures are reviewable ground truth written by a human, not model output.
Nothing here calls a provider: `score_calibration` compares an already-obtained set
of verdicts against the labels, so calibration stays an offline, opt-in activity and
never becomes a release gate.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints

from app.models import StrictModel
from app.semantic_judge import SemanticExpectationType, SemanticVerdict

CALIBRATION_DIRECTORY = Path(__file__).resolve().parent / "calibration_data" / "semantic"

CalibrationCaseId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


class CalibrationTurn(StrictModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=1_000)


class CalibrationCase(StrictModel):
    """One reviewable Turkish example with a human-assigned expected verdict."""

    id: CalibrationCaseId
    expectation_type: SemanticExpectationType
    language_register: str = Field(pattern=r"^(formal|colloquial|noisy|adversarial)$")
    conversation: list[CalibrationTurn] = Field(min_length=1, max_length=8)
    expected_verdict: SemanticVerdict
    rationale: str = Field(min_length=1, max_length=400)


class CalibrationSet(StrictModel):
    cases: list[CalibrationCase] = Field(min_length=1)


class ConfusionCounts(StrictModel):
    """Counts for one expectation type, treating FAIL as the positive class."""

    expectation_type: SemanticExpectationType
    total: int = Field(ge=0)
    agreements: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    matrix: dict[str, int] = Field(default_factory=dict)


class CalibrationScore(StrictModel):
    total: int = Field(ge=0)
    agreements: int = Field(ge=0)
    agreement_rate: float = Field(ge=0.0, le=1.0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    matrix: dict[str, int] = Field(default_factory=dict)
    by_expectation_type: list[ConfusionCounts] = Field(default_factory=list)


class CalibrationCaseNotFoundError(LookupError):
    pass


def load_calibration_set(directory: Path = CALIBRATION_DIRECTORY) -> CalibrationSet:
    """Load every packaged calibration fixture in stable filename order."""

    cases: list[CalibrationCase] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(CalibrationSet.model_validate(payload).cases)

    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("calibration case ids must be unique across fixture files")
    return CalibrationSet(cases=cases)


def _matrix_key(expected: SemanticVerdict, observed: SemanticVerdict) -> str:
    return f"{expected.value}->{observed.value}"


def score_calibration(
    cases: list[CalibrationCase],
    observed: dict[str, SemanticVerdict],
) -> CalibrationScore:
    """Compare human labels against already-obtained verdicts.

    `observed` maps calibration case id to the verdict a judge produced. Every case
    must be present; a missing verdict is a caller error rather than a silent skip,
    so partial runs cannot inflate the agreement rate.
    """

    missing = [case.id for case in cases if case.id not in observed]
    if missing:
        raise CalibrationCaseNotFoundError(
            f"missing observed verdicts for calibration cases: {', '.join(sorted(missing))}"
        )

    matrix: Counter[str] = Counter()
    per_type: dict[SemanticExpectationType, Counter[str]] = {}
    agreements = 0
    false_positives = 0
    false_negatives = 0

    for case in cases:
        actual = observed[case.id]
        key = _matrix_key(case.expected_verdict, actual)
        matrix[key] += 1
        per_type.setdefault(case.expectation_type, Counter())[key] += 1

        if actual is case.expected_verdict:
            agreements += 1
        elif actual is SemanticVerdict.FAIL:
            # Judge claimed a violation the human label does not support.
            false_positives += 1
        elif case.expected_verdict is SemanticVerdict.FAIL:
            # Judge missed a violation the human label asserts.
            false_negatives += 1

    total = len(cases)
    by_type: list[ConfusionCounts] = []
    for expectation_type in sorted(per_type, key=lambda item: item.value):
        counts = per_type[expectation_type]
        type_cases = [case for case in cases if case.expectation_type is expectation_type]
        type_agreements = sum(
            1 for case in type_cases if observed[case.id] is case.expected_verdict
        )
        by_type.append(
            ConfusionCounts(
                expectation_type=expectation_type,
                total=len(type_cases),
                agreements=type_agreements,
                false_positives=sum(
                    1
                    for case in type_cases
                    if observed[case.id] is not case.expected_verdict
                    and observed[case.id] is SemanticVerdict.FAIL
                ),
                false_negatives=sum(
                    1
                    for case in type_cases
                    if observed[case.id] is not case.expected_verdict
                    and case.expected_verdict is SemanticVerdict.FAIL
                ),
                matrix=dict(counts),
            )
        )

    return CalibrationScore(
        total=total,
        agreements=agreements,
        agreement_rate=(agreements / total) if total else 0.0,
        false_positives=false_positives,
        false_negatives=false_negatives,
        matrix=dict(matrix),
        by_expectation_type=by_type,
    )
