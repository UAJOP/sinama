"""CLI safety checks for opt-in semantic calibration."""

import json
import sys
from pathlib import Path

from app import semantic_calibration_cli
from app.semantic_calibration import load_calibration_set
from app.semantic_calibration_runner import SemanticCalibrationRunReport
from app.semantic_judge import SemanticVerdict


def test_cli_refuses_to_run_when_semantic_provider_is_disabled(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("SINAMA_SEMANTIC_JUDGE_PROVIDER", "disabled")
    monkeypatch.delenv("SINAMA_SEMANTIC_JUDGE_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["sinama-semantic-calibrate"])

    exit_code = semantic_calibration_cli.main()
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "disabled" in captured.err.casefold()
    assert "no provider request was made" in captured.err.casefold()


def test_case_selector_rejects_unknown_ids() -> None:
    cases = load_calibration_set().cases

    try:
        semantic_calibration_cli._select_cases(cases, ["missing_case"])
    except ValueError as error:
        assert "missing_case" in str(error)
    else:
        raise AssertionError("unknown calibration id was accepted")


def test_case_selector_preserves_packaged_case_order() -> None:
    cases = load_calibration_set().cases
    requested = [cases[-1].id, cases[0].id]

    selected = semantic_calibration_cli._select_cases(cases, requested)

    assert [case.id for case in selected] == [cases[0].id, cases[-1].id]


def test_calibration_report_json_does_not_require_or_contain_a_secret(tmp_path: Path) -> None:
    case = load_calibration_set().cases[0]
    report = SemanticCalibrationRunReport(
        provider="fake",
        model="fake-model",
        repeats=1,
        case_count=1,
        attempted_evaluations=1,
        completed_evaluations=1,
        error_evaluations=0,
        complete=False,
        score=None,
        observations=[],
        stability=[],
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-model"
    assert case.expected_verdict in set(SemanticVerdict)
    serialized = path.read_text(encoding="utf-8").casefold()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert "bearer" not in serialized
