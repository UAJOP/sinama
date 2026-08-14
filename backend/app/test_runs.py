import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from threading import RLock
from typing import Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from pydantic import Field

from app.agent_adapters import AgentAdapter, DemoAgentAdapter
from app.config import RunStoreBackend, Settings, get_settings
from app.evaluator import EvaluationStatus
from app.http_agent import ExternalAgentConfiguration, build_http_agent_adapter
from app.models import AgentMode, AgentTarget, StrictModel
from app.regression import ComparisonAvailability, RegressionComparisonResponse, build_comparison
from app.scenario_packs import (
    ScenarioPackId,
    ScenarioPackRegistry,
    ScenarioPackSummary,
    scenario_pack_registry,
)
from app.scenario_runner import RunStatus, ScenarioRunResult, scenario_runner
from app.scenarios import Scenario, ScenarioCategory, Severity

logger = logging.getLogger(__name__)

StoreResultT = TypeVar("StoreResultT")


class TestRunLifecycleStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class RunAggregateCounts(StrictModel):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)


class TestRunExecutionError(StrictModel):
    category: Literal["run_orchestration_error"] = "run_orchestration_error"
    reason: str


class ScenarioResultSummary(StrictModel):
    scenario_id: str
    title: str
    category: ScenarioCategory
    status: RunStatus
    severity: Severity | None = None
    turns_executed: int = Field(ge=0)
    failed_check_count: int = Field(ge=0)
    execution_error_category: str | None = None


class TestRunSummary(StrictModel):
    run_id: UUID
    pack_id: str
    pack_name: str
    agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO
    agent_mode: AgentMode
    agent_label: str
    lifecycle_status: TestRunLifecycleStatus
    aggregate: RunAggregateCounts
    completed_scenarios: int = Field(ge=0)
    total_scenarios: int = Field(ge=1)
    is_baseline: bool = False
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: TestRunExecutionError | None = None


class TestRunResultsResponse(StrictModel):
    run: TestRunSummary
    results: list[ScenarioResultSummary]


class CreateTestRunRequest(StrictModel):
    pack_id: ScenarioPackId
    agent_mode: AgentMode = AgentMode.HEALTHY
    agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO
    external_agent: ExternalAgentConfiguration | None = None


@dataclass
class StoredTestRun:
    run_id: UUID
    pack: ScenarioPackSummary
    agent_target: AgentTarget
    agent_mode: AgentMode
    agent_label: str
    lifecycle_status: TestRunLifecycleStatus = TestRunLifecycleStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    results: list[ScenarioRunResult] = field(default_factory=list)
    error: TestRunExecutionError | None = None


class TestRunNotFoundError(LookupError):
    pass


class ScenarioResultNotFoundError(LookupError):
    pass


class InvalidRunAgentConfigurationError(ValueError):
    pass


class RunNotCompletedError(ValueError):
    pass


class CorruptedRunRecordError(RuntimeError):
    """A persisted record could not be validated back into its typed model."""


INTERRUPTED_RUN_REASON = (
    "Test run was interrupted by a service restart and cannot be resumed. Start a new run."
)

TERMINAL_LIFECYCLE_STATUSES = frozenset(
    {TestRunLifecycleStatus.COMPLETED, TestRunLifecycleStatus.ERROR}
)


# --- Shared projections -------------------------------------------------------
# Every run store renders the same API models from these helpers, so memory and
# SQL backends cannot drift into two different notions of "the same run".


def build_run_summary(
    record: StoredTestRun,
    *,
    is_baseline: bool,
    statuses: Sequence[RunStatus] | None = None,
) -> TestRunSummary:
    """Project a stored run onto the public summary model.

    `statuses` lets a store that has deliberately not loaded full result payloads
    supply the per-scenario outcomes it already knows (see `SqlRunStore.get_run`,
    which aggregates them in SQL instead of deserializing every transcript).
    """

    observed = [result.status for result in record.results] if statuses is None else list(statuses)
    return TestRunSummary(
        run_id=record.run_id,
        pack_id=record.pack.id,
        pack_name=record.pack.name,
        agent_target=record.agent_target,
        agent_mode=record.agent_mode,
        agent_label=record.agent_label,
        lifecycle_status=record.lifecycle_status,
        aggregate=RunAggregateCounts(
            total=record.pack.scenario_count,
            passed=sum(status is RunStatus.PASS for status in observed),
            failed=sum(status is RunStatus.FAIL for status in observed),
            errors=sum(status is RunStatus.ERROR for status in observed),
        ),
        completed_scenarios=len(observed),
        total_scenarios=record.pack.scenario_count,
        is_baseline=is_baseline,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error=record.error.model_copy(deep=True) if record.error else None,
    )


def build_result_summary(
    record: StoredTestRun,
    result: ScenarioRunResult,
) -> ScenarioResultSummary:
    metadata = next(
        scenario for scenario in record.pack.scenarios if scenario.scenario_id == result.scenario_id
    )
    return ScenarioResultSummary(
        scenario_id=result.scenario_id,
        title=metadata.title,
        category=metadata.category,
        status=result.status,
        severity=result.severity,
        turns_executed=result.turns_executed,
        failed_check_count=sum(check.status is EvaluationStatus.FAIL for check in result.checks),
        execution_error_category=(result.error.category.value if result.error else None),
    )


def build_results_response(
    record: StoredTestRun,
    *,
    is_baseline: bool,
) -> TestRunResultsResponse:
    return TestRunResultsResponse(
        run=build_run_summary(record, is_baseline=is_baseline),
        results=[build_result_summary(record, result) for result in record.results],
    )


def build_comparison_response(
    record: StoredTestRun,
    baseline_run_id: UUID | None,
    baseline_record: StoredTestRun | None,
) -> RegressionComparisonResponse:
    """Resolve comparison availability, then delegate scoring to `build_comparison`.

    Regression semantics live in `app.regression` only - this decides *whether* a
    comparison is possible, never what the numbers mean.
    """

    if baseline_run_id is None:
        return RegressionComparisonResponse(status=ComparisonAvailability.NO_BASELINE)
    # Checked before `baseline_record`: a run compared against itself needs no
    # loaded baseline payloads, so stores are free to leave that argument None.
    if baseline_run_id == record.run_id:
        return RegressionComparisonResponse(status=ComparisonAvailability.IS_BASELINE)
    if baseline_record is None:
        return RegressionComparisonResponse(status=ComparisonAvailability.NO_BASELINE)

    baseline_scenario_ids = {scenario.scenario_id for scenario in baseline_record.pack.scenarios}
    current_scenario_ids = {scenario.scenario_id for scenario in record.pack.scenarios}
    if baseline_scenario_ids != current_scenario_ids:
        return RegressionComparisonResponse(status=ComparisonAvailability.INCOMPATIBLE)

    return RegressionComparisonResponse(
        status=ComparisonAvailability.AVAILABLE,
        comparison=build_comparison(
            baseline_run_id=baseline_run_id,
            current_run_id=record.run_id,
            pack_id=record.pack.id,
            baseline_results=baseline_record.results,
            current_results=record.results,
        ),
    )


class RunStore(Protocol):
    """Storage boundary shared by the in-memory and SQL run stores.

    Every method is synchronous: FastAPI already runs `def` endpoints in a
    threadpool, and `RunService` moves its calls off the event loop explicitly.
    """

    def create_run(
        self,
        pack: ScenarioPackSummary,
        agent_mode: AgentMode,
        *,
        agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO,
        agent_label: str | None = None,
    ) -> TestRunSummary: ...

    def mark_running(self, run_id: UUID) -> None: ...

    def add_result(self, run_id: UUID, result: ScenarioRunResult) -> None: ...

    def mark_completed(self, run_id: UUID) -> None: ...

    def mark_error(self, run_id: UUID, reason: str) -> None: ...

    def get_run(self, run_id: UUID) -> TestRunSummary: ...

    def get_results(self, run_id: UUID) -> TestRunResultsResponse: ...

    def get_result(self, run_id: UUID, scenario_id: str) -> ScenarioRunResult: ...

    def list_runs(self, limit: int = 20) -> list[TestRunSummary]: ...

    def set_baseline(self, run_id: UUID) -> TestRunSummary: ...

    def get_comparison(self, run_id: UUID) -> RegressionComparisonResponse: ...

    def recover_interrupted_runs(self) -> int: ...

    def clear(self) -> None: ...


class InMemoryRunStore:
    """Thread-safe, bounded in-memory storage for single-process demo runs."""

    def __init__(self, max_runs: int = 20) -> None:
        if max_runs < 1:
            raise ValueError("max_runs must be at least 1")
        self._max_runs = max_runs
        self._runs: OrderedDict[UUID, StoredTestRun] = OrderedDict()
        self._baselines: dict[str, UUID] = {}
        self._lock = RLock()

    def create_run(
        self,
        pack: ScenarioPackSummary,
        agent_mode: AgentMode,
        *,
        agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO,
        agent_label: str | None = None,
    ) -> TestRunSummary:
        with self._lock:
            record = StoredTestRun(
                run_id=uuid4(),
                pack=pack.model_copy(deep=True),
                agent_target=agent_target,
                agent_mode=agent_mode,
                agent_label=agent_label or agent_mode.value,
            )
            self._runs[record.run_id] = record
            self._prune_locked()
            return self._summary_locked(record)

    def mark_running(self, run_id: UUID) -> None:
        with self._lock:
            record = self._get_locked(run_id)
            record.lifecycle_status = TestRunLifecycleStatus.RUNNING
            record.started_at = datetime.now(UTC)

    def add_result(self, run_id: UUID, result: ScenarioRunResult) -> None:
        with self._lock:
            record = self._get_locked(run_id)
            record.results.append(result.model_copy(deep=True))

    def mark_completed(self, run_id: UUID) -> None:
        with self._lock:
            record = self._get_locked(run_id)
            record.lifecycle_status = TestRunLifecycleStatus.COMPLETED
            record.completed_at = datetime.now(UTC)
            self._prune_locked()

    def mark_error(self, run_id: UUID, reason: str) -> None:
        with self._lock:
            record = self._get_locked(run_id)
            record.lifecycle_status = TestRunLifecycleStatus.ERROR
            record.completed_at = datetime.now(UTC)
            record.error = TestRunExecutionError(reason=reason)
            self._prune_locked()

    def get_run(self, run_id: UUID) -> TestRunSummary:
        with self._lock:
            return self._summary_locked(self._get_locked(run_id))

    def get_results(self, run_id: UUID) -> TestRunResultsResponse:
        with self._lock:
            record = self._get_locked(run_id)
            return build_results_response(record, is_baseline=self._is_baseline_locked(record))

    def list_runs(self, limit: int = 20) -> list[TestRunSummary]:
        with self._lock:
            recent = list(self._runs.values())[-limit:] if limit > 0 else []
            return [self._summary_locked(record) for record in reversed(recent)]

    def recover_interrupted_runs(self) -> int:
        """No-op: an in-memory store always starts empty, so nothing can be orphaned."""

        return 0

    def get_result(self, run_id: UUID, scenario_id: str) -> ScenarioRunResult:
        with self._lock:
            record = self._get_locked(run_id)
            result = next(
                (item for item in record.results if item.scenario_id == scenario_id),
                None,
            )
            if result is None:
                raise ScenarioResultNotFoundError(scenario_id)
            return result.model_copy(deep=True)

    def set_baseline(self, run_id: UUID) -> TestRunSummary:
        with self._lock:
            record = self._get_locked(run_id)
            if record.lifecycle_status is not TestRunLifecycleStatus.COMPLETED:
                raise RunNotCompletedError("Only a completed run can be set as a baseline.")
            self._baselines[record.pack.id] = run_id
            return self._summary_locked(record)

    def get_comparison(self, run_id: UUID) -> RegressionComparisonResponse:
        with self._lock:
            record = self._get_locked(run_id)
            baseline_id = self._baselines.get(record.pack.id)
            baseline_record = self._runs.get(baseline_id) if baseline_id is not None else None
            if baseline_id is not None and baseline_id != run_id and baseline_record is None:
                # The baseline run aged out of the bounded store - self-heal the
                # stale mapping instead of leaving a dangling reference around.
                del self._baselines[record.pack.id]
                baseline_id = None
            return build_comparison_response(record, baseline_id, baseline_record)

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._baselines.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)

    def _get_locked(self, run_id: UUID) -> StoredTestRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise TestRunNotFoundError(str(run_id)) from error

    def _is_baseline_locked(self, record: StoredTestRun) -> bool:
        return self._baselines.get(record.pack.id) == record.run_id

    def _summary_locked(self, record: StoredTestRun) -> TestRunSummary:
        return build_run_summary(record, is_baseline=self._is_baseline_locked(record))

    def _prune_locked(self) -> None:
        while len(self._runs) > self._max_runs:
            candidate = next(
                (
                    run_id
                    for run_id, record in self._runs.items()
                    if record.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES
                ),
                None,
            )
            if candidate is None:
                break
            del self._runs[candidate]


class ScenarioRunExecutor(Protocol):
    async def run(
        self,
        scenario: Scenario | None,
        adapter: AgentAdapter,
        *,
        turn_timeout_seconds: float = 5.0,
    ) -> ScenarioRunResult: ...


DemoAgentAdapterFactory = Callable[[AgentMode], AgentAdapter]
HttpAgentAdapterFactory = Callable[[ExternalAgentConfiguration], AgentAdapter]
ScenarioAdapterFactory = Callable[[], AgentAdapter]


class RunService:
    def __init__(
        self,
        *,
        registry: ScenarioPackRegistry = scenario_pack_registry,
        store: RunStore,
        runner: ScenarioRunExecutor = scenario_runner,
        adapter_factory: DemoAgentAdapterFactory = DemoAgentAdapter,
        http_adapter_factory: HttpAgentAdapterFactory = build_http_agent_adapter,
    ) -> None:
        self._registry = registry
        self._store = store
        self._runner = runner
        self._adapter_factory = adapter_factory
        self._http_adapter_factory = http_adapter_factory
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    @staticmethod
    async def _store_call(operation: Callable[[], StoreResultT]) -> StoreResultT:
        """Run a synchronous store operation without blocking the event loop.

        The SQL store performs real network I/O; the in-memory store is trivial
        but thread-safe, so both are safe to hand to a worker thread.
        """

        return await asyncio.to_thread(operation)

    async def create_run(
        self,
        pack_id: str,
        agent_mode: AgentMode,
        *,
        agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO,
        external_agent: ExternalAgentConfiguration | None = None,
    ) -> TestRunSummary:
        pack = self._registry.get_pack(pack_id)
        scenarios = self._registry.load_scenarios(pack_id)
        if agent_target is AgentTarget.BUILT_IN_DEMO:
            if external_agent is not None:
                raise InvalidRunAgentConfigurationError(
                    "Built-in demo runs cannot include external agent configuration."
                )
            adapter_factory: ScenarioAdapterFactory = partial(
                self._adapter_factory,
                agent_mode,
            )
            agent_label = agent_mode.value
        else:
            if external_agent is None:
                raise InvalidRunAgentConfigurationError(
                    "External HTTP runs require endpoint configuration."
                )
            ephemeral_configuration = external_agent.model_copy(deep=True)
            adapter_factory = partial(
                self._http_adapter_factory,
                ephemeral_configuration,
            )
            agent_label = AgentTarget.EXTERNAL_HTTP.value

        summary = await self._store_call(
            partial(
                self._store.create_run,
                pack,
                agent_mode,
                agent_target=agent_target,
                agent_label=agent_label,
            )
        )
        task = asyncio.create_task(
            self._execute_run(summary.run_id, scenarios, adapter_factory),
            name=f"sinama-run-{summary.run_id}",
        )
        self._tasks[summary.run_id] = task
        task.add_done_callback(partial(self._forget_task, summary.run_id))
        return summary

    async def wait_for_completion(self, run_id: UUID) -> TestRunSummary:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)
        return await self._store_call(partial(self._store.get_run, run_id))

    async def _execute_run(
        self,
        run_id: UUID,
        scenarios: list[Scenario],
        adapter_factory: ScenarioAdapterFactory,
    ) -> None:
        try:
            await self._store_call(partial(self._store.mark_running, run_id))
            for scenario in scenarios:
                result = await self._runner.run(
                    scenario,
                    adapter_factory(),
                )
                await self._store_call(partial(self._store.add_result, run_id, result))
            await self._store_call(partial(self._store.mark_completed, run_id))
        except Exception:
            logger.exception("Unexpected orchestration error in test run %s", run_id)
            try:
                await self._store_call(
                    partial(
                        self._store.mark_error,
                        run_id,
                        "Test run orchestration failed. Retry the run or inspect server logs.",
                    )
                )
            except Exception:
                # A store that is itself unavailable must not mask the original
                # orchestration failure or leave an unhandled task exception.
                logger.exception("Could not persist the error state for test run %s", run_id)

    def _forget_task(self, run_id: UUID, task: asyncio.Task[None]) -> None:
        current = self._tasks.get(run_id)
        if current is task:
            self._tasks.pop(run_id, None)


def build_run_store(settings: Settings | None = None) -> RunStore:
    """Select the configured run store.

    The SQL store is imported lazily so that a memory-backed deployment never
    needs the database driver installed, and so this module stays importable
    while `app.db.sql_run_store` imports its record types from here.
    """

    resolved = settings or get_settings()
    if resolved.run_store_backend is RunStoreBackend.MEMORY:
        return InMemoryRunStore(max_runs=resolved.run_history_limit)

    from app.db.engine import create_run_store_engine
    from app.db.sql_run_store import SqlRunStore

    return SqlRunStore(create_run_store_engine(resolved))


run_store: RunStore = build_run_store()
run_service = RunService(store=run_store)
