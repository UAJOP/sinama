import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scenarios import load_scenario

SCENARIO_DIR = Path(__file__).parents[2] / "scenarios" / "insurance"


def test_valid_scenario_fixtures_parse() -> None:
    fixtures = sorted(SCENARIO_DIR.glob("INS-*.json"))

    assert len(fixtures) == 5
    scenarios = [load_scenario(path) for path in fixtures]
    assert [scenario.id for scenario in scenarios] == [
        "INS-001",
        "INS-002",
        "INS-003",
        "INS-004",
        "INS-005",
    ]


def test_malformed_scenario_fixture_fails_validation(tmp_path: Path) -> None:
    malformed = {
        "id": "unsafe-id",
        "version": "first",
        "title": "Eksik fixture",
        "unexpected": "field",
    }
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_scenario(path)
