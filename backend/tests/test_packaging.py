"""Guard against requirements.txt / pyproject.toml runtime dependency drift.

`pyproject.toml` is the source of truth for local installs (`pip install -e .`),
but Railway installs from `requirements.txt`. When the two disagree, the failure
only shows up as a `ModuleNotFoundError` at production startup - which is exactly
how the persistence dependencies were missed.

`tomllib` is stdlib on Python 3.11+, so this check adds no dependency of its own.
"""

import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = BACKEND_ROOT / "pyproject.toml"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"


def _pyproject_runtime_dependencies() -> set[str]:
    with PYPROJECT.open("rb") as handle:
        return set(tomllib.load(handle)["project"]["dependencies"])


def _requirements_dependencies() -> list[str]:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    return [
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def test_requirements_matches_pyproject_runtime_dependencies() -> None:
    """Every production dependency must be installable from requirements.txt.

    Compared as exact specifier strings, so a version-range change on one side
    alone also fails rather than silently shipping a different resolution.
    """

    declared = _pyproject_runtime_dependencies()
    pinned = set(_requirements_dependencies())

    missing = declared - pinned
    extra = pinned - declared
    assert not missing, (
        f"requirements.txt is missing runtime dependencies {sorted(missing)}; "
        "Railway installs from this file and would fail at startup."
    )
    assert not extra, (
        f"requirements.txt declares {sorted(extra)} which pyproject.toml does not; "
        "add them to [project].dependencies or remove them here."
    )


def test_requirements_has_no_duplicate_entries() -> None:
    entries = _requirements_dependencies()

    assert len(entries) == len(set(entries)), "duplicate entries in requirements.txt"


def test_dev_only_dependencies_are_not_shipped_to_production() -> None:
    """Test/lint tooling must not leak into the production install."""

    with PYPROJECT.open("rb") as handle:
        dev = tomllib.load(handle)["project"]["optional-dependencies"]["dev"]

    dev_names = {_distribution_name(entry) for entry in dev}
    shipped = {_distribution_name(entry) for entry in _requirements_dependencies()}

    assert not (dev_names & shipped), (
        f"dev-only dependencies {sorted(dev_names & shipped)} are in requirements.txt"
    )


def _distribution_name(specifier: str) -> str:
    """Reduce `psycopg[binary]>=3.2,<4` to `psycopg`."""

    for boundary in (">=", "<=", "==", "~=", "!=", ">", "<", "["):
        specifier = specifier.split(boundary, 1)[0]
    return specifier.strip().casefold()
