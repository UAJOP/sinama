from sqlalchemy import create_engine

from app.db.engine import RUN_STORE_RLS_TABLES, enable_run_store_rls


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one(self) -> str | None:
        return self._value


class _FakeConnection:
    def __init__(self, existing_tables: set[str]) -> None:
        self.existing_tables = existing_tables
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str, parameters: tuple[str, ...] | None = None):
        self.statements.append(statement)
        if statement.startswith("SELECT to_regclass"):
            assert parameters is not None
            qualified = parameters[0]
            table_name = qualified.rsplit(".", maxsplit=1)[-1]
            return _FakeResult(qualified if table_name in self.existing_tables else None)
        return _FakeResult(None)


class _FakeBegin:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeDialect:
    name = "postgresql"


class _FakePostgresEngine:
    dialect = _FakeDialect()

    def __init__(self, existing_tables: set[str]) -> None:
        self.connection = _FakeConnection(existing_tables)

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


def test_enable_run_store_rls_is_noop_for_non_postgres() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        assert enable_run_store_rls(engine) == 0
    finally:
        engine.dispose()


def test_enable_run_store_rls_hardens_every_existing_table() -> None:
    engine = _FakePostgresEngine(set(RUN_STORE_RLS_TABLES))

    hardened = enable_run_store_rls(engine)  # type: ignore[arg-type]

    assert hardened == len(RUN_STORE_RLS_TABLES)
    alters = [statement for statement in engine.connection.statements if statement.startswith("ALTER")]
    assert alters == [
        f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
        for table_name in RUN_STORE_RLS_TABLES
    ]


def test_enable_run_store_rls_skips_tables_that_do_not_exist_yet() -> None:
    engine = _FakePostgresEngine({"test_runs"})

    hardened = enable_run_store_rls(engine)  # type: ignore[arg-type]

    assert hardened == 1
    alters = [statement for statement in engine.connection.statements if statement.startswith("ALTER")]
    assert alters == ['ALTER TABLE public."test_runs" ENABLE ROW LEVEL SECURITY']
