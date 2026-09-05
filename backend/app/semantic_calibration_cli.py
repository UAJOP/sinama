"""Command-line entry point for opt-in semantic calibration runs."""

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import Settings
from app.semantic_calibration import CalibrationCase, load_calibration_set
from app.semantic_calibration_runner import run_semantic_calibration
from app.semantic_judge import SemanticJudge
from app.semantic_judge_factory import build_semantic_judge
from app.semantic_judge_local import (
    DEFAULT_OLLAMA_BASE_URL,
    LocalJudgeConfigurationError,
    OllamaSemanticJudge,
)

_DEFAULT_OUTPUT = Path("reports/semantic-calibration.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sinama-semantic-calibrate",
        description=(
            "Run SINAMA's hand-labeled Turkish semantic calibration set against the "
            "explicitly configured shadow judge. Provider use is opt-in and env-backed."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        choices=range(1, 6),
        metavar="1-5",
        help="Run each selected calibration case 1-5 times to measure stability.",
    )
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        default=[],
        help="Run only this calibration case id. May be supplied multiple times.",
    )
    parser.add_argument(
        "--local-ollama",
        action="store_true",
        help=(
            "Calibrate against a local Ollama daemon instead of the configured cloud "
            "provider. Requires no API key and performs no paid request. This is "
            "calibration tooling only and never affects production semantic runs."
        ),
    )
    parser.add_argument(
        "--ollama-model",
        default="qwen3:4b",
        help="Local model tag to calibrate with (default: qwen3:4b).",
    )
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help=f"Loopback Ollama base URL (default: {DEFAULT_OLLAMA_BASE_URL}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="JSON report path (default: reports/semantic-calibration.json).",
    )
    return parser


def _select_cases(cases: list[CalibrationCase], case_ids: list[str]) -> list[CalibrationCase]:
    if not case_ids:
        return cases
    requested = set(case_ids)
    selected = [case for case in cases if case.id in requested]
    missing = sorted(requested - {case.id for case in selected})
    if missing:
        raise ValueError(f"unknown calibration case ids: {', '.join(missing)}")
    return selected


def main() -> int:
    parser = _parser()
    args = parser.parse_args()

    try:
        settings = Settings()
        judge: SemanticJudge | None
        if args.local_ollama:
            # Built directly here on purpose: the local judge is deliberately absent
            # from `build_semantic_judge`, so it can never serve a production run.
            judge = OllamaSemanticJudge(
                model=args.ollama_model,
                timeout_seconds=settings.semantic_judge_local_timeout_seconds,
                max_input_chars=settings.semantic_judge_max_input_chars,
                base_url=args.ollama_url,
            )
        else:
            judge = build_semantic_judge(settings)
    except (LocalJudgeConfigurationError, ValueError) as error:
        print(f"Calibration configuration error: {error}", file=sys.stderr)
        return 2

    if judge is None:
        print(
            "Semantic calibration is disabled. Either pass --local-ollama for a zero-cost "
            "local run, or set SINAMA_SEMANTIC_JUDGE_PROVIDER and the provider key in your "
            "local environment. No provider request was made.",
            file=sys.stderr,
        )
        return 2

    calibration = load_calibration_set()
    try:
        cases = _select_cases(calibration.cases, args.case_ids)
    except ValueError as error:
        parser.error(str(error))

    report = asyncio.run(
        run_semantic_calibration(
            judge,
            cases,
            repeats=args.repeats,
            timeout_seconds=(
                settings.semantic_judge_local_timeout_seconds
                if args.local_ollama
                else settings.semantic_judge_timeout_seconds
            ),
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    print(
        f"Semantic calibration: {report.completed_evaluations}/{report.attempted_evaluations} "
        f"evaluations completed · provider={report.provider} · model={report.model}"
    )
    if report.score is not None:
        print(
            f"Agreement: {report.score.agreements}/{report.score.total} "
            f"({report.score.agreement_rate:.1%}) · false positives={report.score.false_positives} "
            f"· false negatives={report.score.false_negatives}"
        )
    else:
        print("Agreement not scored because at least one requested evaluation was incomplete.")
    print(f"Report: {args.output}")
    return 0 if report.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
