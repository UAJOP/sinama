"""Regression tests for the Supabase RLS hardening migration."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0003_enable_rls.py"
)


def _load_migration():
    spec = spec_from_file_location("sinama_migration_0003", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(dialect_name: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))


def test_upgrade_enables_rls_for_every_persistence_table(monkeypatch) -> None:
    migration = _load_migration()
    execute = Mock()
    monkeypatch.setattr(migration.op, "get_bind", lambda: _bind("postgresql"))
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.upgrade()

    statements = [call.args[0] for call in execute.call_args_list]
    assert statements == [
        'ALTER TABLE public."test_runs" ENABLE ROW LEVEL SECURITY',
        'ALTER TABLE public."scenario_results" ENABLE ROW LEVEL SECURITY',
        'ALTER TABLE public."run_baselines" ENABLE ROW LEVEL SECURITY',
    ]


def test_downgrade_disables_rls_in_reverse_order(monkeypatch) -> None:
    migration = _load_migration()
    execute = Mock()
    monkeypatch.setattr(migration.op, "get_bind", lambda: _bind("postgresql"))
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.downgrade()

    statements = [call.args[0] for call in execute.call_args_list]
    assert statements == [
        'ALTER TABLE public."run_baselines" DISABLE ROW LEVEL SECURITY',
        'ALTER TABLE public."scenario_results" DISABLE ROW LEVEL SECURITY',
        'ALTER TABLE public."test_runs" DISABLE ROW LEVEL SECURITY',
    ]


def test_rls_migration_is_noop_outside_postgresql(monkeypatch) -> None:
    migration = _load_migration()
    execute = Mock()
    monkeypatch.setattr(migration.op, "get_bind", lambda: _bind("sqlite"))
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.upgrade()
    migration.downgrade()

    execute.assert_not_called()
