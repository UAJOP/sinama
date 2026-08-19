"""SQLAlchemy-backed run store.

Mirrors `InMemoryRunStore` for normal run/history operations and renders API
models through shared projections in `app.test_runs`. Trend listing reads only
small denormalized result metadata; it never deserializes full transcript/check
payloads merely to render the trend surface.

All methods are synchronous and perform blocking I/O. Callers are responsible for
keeping them off the asyncio event loop - `RunService` does this via
`asyncio.to_thread`, and FastAPI already runs `def` endpoints in a threadpool.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RunBaselineRow, ScenarioResultRow, TestRunRow
from app.models import AgentMode, AgentTarget
from app.regression import (
    RegressionComparisonResponse,
    critical_failure_fingerprints,
    scenario_goal_score,
)
from app.scenario_packs import ScenarioPackSummary
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.scenarios import Severity
from app.test_runs import (
    INTERRUPTED_RUN_REASON,
    CorruptedRunRecordError,
    ExplicitRunComparisonResponse,
    RunNotCompletedError,
    ScenarioResultNotFoundError,
    StoredTestRun,
    TestRunExecutionError,
    TestRunLifecycleStatus,
    TestRunNotFoundError,
    TestRunResultsResponse,
    TestRunSummary,
    build_comparison_response,
    build_explicit_comparison,
    build_results_response,
    build_run_summary,
)
from app.trends import RunTrendResponse, TrendRunInput, build_run_trends

logger = logging.getLogger(__name__)

_NON_TERMINAL_STATUSES = (
    TestRunLifecycleStatus.QUEUED.value,
    TestRunLifecycleStatus.RUNNING.value,
)
_TERMINAL_STATUSES = (
    TestRunLifecycleStatus.COMPLETED.value,
    TestRunLifecycleStatus.ERROR.value,
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_utc(value: datetime | None) -> datetime:
    normalized = _as_utc(value)
    if normalized is None:
        raise CorruptedRunRecordError("Stored run is missing its creation timestamp.")
    return normalized


class SqlRunStore:
    """Durable run history. Unlike the memory store, nothing is pruned on write."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    # --- writes ---------------------------------------------------------------

    def create_run(
        self,
        pack: ScenarioPackSummary,
        agent_mode: AgentMode,
        *,
        agent_target: AgentTarget = AgentTarget.BUILT_IN_DEMO,
        agent_label: str | None = None,
        agent_version: str | None = None,
    ) -> TestRunSummary:
        record = StoredTestRun(
            run_id=uuid4(),
            pack=pack.model_copy(deep=True),
            agent_target=agent_target,
            agent_mode=agent_mode,
            agent_label=agent_label or agent_mode.value,
            agent_version=agent_version,
        )
        with self._sessions.begin() as session:
            session.add(
                TestRunRow(
                    run_id=record.run_id,
                    pack_id=record.pack.id,
                    pack_name=record.pack.name,
                    pack_snapshot=record.pack.model_dump(mode="json"),
                    agent_target=record.agent_target.value,
                    agent_mode=record.agent_mode.value,
                    agent_label=record.agent_label,
                    agent_version=record.agent_version,
                    lifecycle_status=record.lifecycle_status.value,
                    created_at=record.created_at,
                    started_at=None,
                    completed_at=None,
                    error=None,
                )
            )
        return build_run_summary(record, is_baseline=False, statuses=[])

    def mark_running(self, run_id: UUID) -> None:
        self._update_lifecycle(
            run_id,
            lifecycle_status=TestRunLifecycleStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    def mark_completed(self, run_id: UUID) -> None:
        self._update_lifecycle(
            run_id,
            lifecycle_status=TestRunLifecycleStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )

    def mark_error(self, run_id: UUID, reason: str) -> None:
        self._update_lifecycle(
            run_id,
            lifecycle_status=TestRunLifecycleStatus.ERROR,
            completed_at=datetime.now(UTC),
            error=TestRunExecutionError(reason=reason).model_dump(mode="json"),
        )

    def add_result(self, run_id: UUID, result: ScenarioRunResult) -> None:
        with self._sessions.begin() as session:
            self._require_run_row(session, run_id)
            next_position = session.scalar(
                select(func.coalesce(func.max(ScenarioResultRow.position), -1) + 1).where(
                    ScenarioResultRow.run_id == run_id
                )
            )
            session.add(
                ScenarioResultRow(
                    run_id=run_id,
                    position=next_position or 0,
                    scenario_id=result.scenario_id,
                    status=result.status.value,
                    severity=result.severity.value if result.severity is not None else None,
                    goal_score=scenario_goal_score(result),
                    critical_failure_keys=sorted(critical_failure_fingerprints(result)),
                    payload=result.model_dump(mode="json"),
                )
            )

    def set_baseline(self, run_id: UUID) -> TestRunSummary:
        with self._sessions.begin() as session:
            row = self._require_run_row(session, run_id)
            if row.lifecycle_status != TestRunLifecycleStatus.COMPLETED.value:
                raise RunNotCompletedError("Only a completed run can be set as a baseline.")
            session.execute(delete(RunBaselineRow).where(RunBaselineRow.pack_id == row.pack_id))
            session.add(
                RunBaselineRow(
                    pack_id=row.pack_id,
                    run_id=run_id,
                    updated_at=datetime.now(UTC),
                )
            )
            record = self._record_from_row(row, [])
            statuses = self._statuses_for(session, [run_id]).get(run_id, [])
        return build_run_summary(record, is_baseline=True, statuses=statuses)

    def recover_interrupted_runs(self) -> int:
        with self._sessions.begin() as session:
            result = session.connection().execute(
                update(TestRunRow)
                .where(TestRunRow.lifecycle_status.in_(_NON_TERMINAL_STATUSES))
                .values(
                    lifecycle_status=TestRunLifecycleStatus.ERROR.value,
                    completed_at=datetime.now(UTC),
                    error=TestRunExecutionError(reason=INTERRUPTED_RUN_REASON).model_dump(
                        mode="json"
                    ),
                )
            )
            return result.rowcount or 0

    def clear(self) -> None:
        with self._sessions.begin() as session:
            session.execute(delete(RunBaselineRow))
            session.execute(delete(ScenarioResultRow))
            session.execute(delete(TestRunRow))

    # --- reads ----------------------------------------------------------------

    def get_run(self, run_id: UUID) -> TestRunSummary:
        with self._sessions() as session:
            row = self._require_run_row(session, run_id)
            statuses = self._statuses_for(session, [run_id]).get(run_id, [])
            baselines = self._baselines_for(session, [row.pack_id])
            record = self._record_from_row(row, [])
        return build_run_summary(
            record,
            is_baseline=baselines.get(row.pack_id) == run_id,
            statuses=statuses,
        )

    def get_results(self, run_id: UUID) -> TestRunResultsResponse:
        with self._sessions() as session:
            row = self._require_run_row(session, run_id)
            record = self._record_from_row(row, self._results_for(session, run_id))
            baselines = self._baselines_for(session, [row.pack_id])
        return build_results_response(record, is_baseline=baselines.get(row.pack_id) == run_id)

    def get_result(self, run_id: UUID, scenario_id: str) -> ScenarioRunResult:
        with self._sessions() as session:
            self._require_run_row(session, run_id)
            payload = session.scalar(
                select(ScenarioResultRow.payload)
                .where(
                    ScenarioResultRow.run_id == run_id,
                    ScenarioResultRow.scenario_id == scenario_id,
                )
                .order_by(ScenarioResultRow.position)
                .limit(1)
            )
        if payload is None:
            raise ScenarioResultNotFoundError(scenario_id)
        return self._load_result(payload)

    def list_runs(self, limit: int = 20) -> list[TestRunSummary]:
        if limit < 1:
            return []
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(TestRunRow)
                    .order_by(TestRunRow.created_at.desc(), TestRunRow.run_id.desc())
                    .limit(limit)
                )
            )
            if not rows:
                return []
            statuses = self._statuses_for(session, [row.run_id for row in rows])
            baselines = self._baselines_for(session, [row.pack_id for row in rows])
        return [
            build_run_summary(
                self._record_from_row(row, []),
                is_baseline=baselines.get(row.pack_id) == row.run_id,
                statuses=statuses.get(row.run_id, []),
            )
            for row in rows
        ]

    def list_trends(self, pack_id: str, limit: int = 20) -> RunTrendResponse:
        if limit < 1:
            return RunTrendResponse(pack_id=pack_id, points=[])

        with self._sessions() as session:
            newest_rows = list(
                session.scalars(
                    select(TestRunRow)
                    .where(
                        TestRunRow.pack_id == pack_id,
                        TestRunRow.lifecycle_status.in_(_TERMINAL_STATUSES),
                    )
                    .order_by(TestRunRow.created_at.desc(), TestRunRow.run_id.desc())
                    .limit(limit)
                )
            )
            if not newest_rows:
                return RunTrendResponse(pack_id=pack_id, points=[])

            rows = list(reversed(newest_rows))
            metadata = self._trend_metadata_for(session, [row.run_id for row in rows])
            baseline_id = self._baselines_for(session, [pack_id]).get(pack_id)

            trend_inputs: list[TrendRunInput] = []
            for row in rows:
                record = self._record_from_row(row, [])
                statuses, goal_scores, severities, critical_keys = metadata.get(
                    row.run_id,
                    ([], [], [], set()),
                )
                trend_inputs.append(
                    TrendRunInput(
                        run_id=row.run_id,
                        pack_id=row.pack_id,
                        agent_label=row.agent_label,
                        agent_version=row.agent_version,
                        lifecycle_status=(
                            "completed"
                            if row.lifecycle_status == TestRunLifecycleStatus.COMPLETED.value
                            else "error"
                        ),
                        created_at=_require_utc(row.created_at).isoformat(),
                        is_baseline=baseline_id == row.run_id,
                        scenario_ids=tuple(
                            scenario.scenario_id for scenario in record.pack.scenarios
                        ),
                        statuses=tuple(statuses),
                        goal_scores=tuple(goal_scores),
                        severities=tuple(severities),
                        critical_failure_keys=frozenset(critical_keys),
                    )
                )

        return build_run_trends(pack_id, trend_inputs)

    def get_comparison(self, run_id: UUID) -> RegressionComparisonResponse:
        with self._sessions() as session:
            row = self._require_run_row(session, run_id)
            baseline_run_id = self._baselines_for(session, [row.pack_id]).get(row.pack_id)

            baseline_record: StoredTestRun | None = None
            if baseline_run_id is not None and baseline_run_id != run_id:
                baseline_row = session.get(TestRunRow, baseline_run_id)
                if baseline_row is not None:
                    baseline_record = self._record_from_row(
                        baseline_row, self._results_for(session, baseline_run_id)
                    )
                else:
                    baseline_run_id = None

            record = self._record_from_row(
                row,
                self._results_for(session, run_id) if baseline_record is not None else [],
            )
        return build_comparison_response(record, baseline_run_id, baseline_record)

    def compare_runs(
        self,
        reference_run_id: UUID,
        current_run_id: UUID,
    ) -> ExplicitRunComparisonResponse:
        with self._sessions() as session:
            reference_row = self._require_run_row(session, reference_run_id)
            current_row = self._require_run_row(session, current_run_id)

            reference = self._record_from_row(
                reference_row, self._results_for(session, reference_run_id)
            )
            current = self._record_from_row(
                current_row, self._results_for(session, current_run_id)
            )
            baselines = self._baselines_for(
                session, [reference_row.pack_id, current_row.pack_id]
            )

        return ExplicitRunComparisonResponse(
            reference_run=build_run_summary(
                reference,
                is_baseline=baselines.get(reference_row.pack_id) == reference_run_id,
            ),
            current_run=build_run_summary(
                current,
                is_baseline=baselines.get(current_row.pack_id) == current_run_id,
            ),
            comparison=build_explicit_comparison(reference, current),
        )

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _require_run_row(session: Session, run_id: UUID) -> TestRunRow:
        row = session.get(TestRunRow, run_id)
        if row is None:
            raise TestRunNotFoundError(str(run_id))
        return row

    def _update_lifecycle(
        self,
        run_id: UUID,
        *,
        lifecycle_status: TestRunLifecycleStatus,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {"lifecycle_status": lifecycle_status.value}
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if error is not None:
            values["error"] = error
        with self._sessions.begin() as session:
            result = session.connection().execute(
                update(TestRunRow).where(TestRunRow.run_id == run_id).values(**values)
            )
            if result.rowcount == 0:
                raise TestRunNotFoundError(str(run_id))

    @staticmethod
    def _statuses_for(
        session: Session,
        run_ids: Sequence[UUID],
    ) -> dict[UUID, list[RunStatus]]:
        if not run_ids:
            return {}
        rows = session.execute(
            select(ScenarioResultRow.run_id, ScenarioResultRow.status)
            .where(ScenarioResultRow.run_id.in_(run_ids))
            .order_by(ScenarioResultRow.run_id, ScenarioResultRow.position)
        )
        grouped: dict[UUID, list[RunStatus]] = {}
        for run_id, status in rows:
            grouped.setdefault(run_id, []).append(RunStatus(status))
        return grouped

    @staticmethod
    def _trend_metadata_for(
        session: Session,
        run_ids: Sequence[UUID],
    ) -> dict[UUID, tuple[list[RunStatus], list[int], list[Severity], set[str]]]:
        if not run_ids:
            return {}
        rows = session.execute(
            select(
                ScenarioResultRow.run_id,
                ScenarioResultRow.status,
                ScenarioResultRow.goal_score,
                ScenarioResultRow.severity,
                ScenarioResultRow.critical_failure_keys,
            )
            .where(ScenarioResultRow.run_id.in_(run_ids))
            .order_by(ScenarioResultRow.run_id, ScenarioResultRow.position)
        )
        grouped: dict[UUID, tuple[list[RunStatus], list[int], list[Severity], set[str]]] = {}
        for run_id, status, goal_score, severity, critical_keys in rows:
            entry = grouped.setdefault(run_id, ([], [], [], set()))
            entry[0].append(RunStatus(status))
            entry[1].append(goal_score if isinstance(goal_score, int) else 0)
            if isinstance(severity, str):
                entry[2].append(Severity(severity))
            if isinstance(critical_keys, list):
                entry[3].update(key for key in critical_keys if isinstance(key, str))
        return grouped

    @staticmethod
    def _baselines_for(session: Session, pack_ids: Sequence[str]) -> dict[str, UUID]:
        if not pack_ids:
            return {}
        rows = session.execute(
            select(RunBaselineRow.pack_id, RunBaselineRow.run_id).where(
                RunBaselineRow.pack_id.in_(set(pack_ids))
            )
        )
        return {pack_id: run_id for pack_id, run_id in rows}

    def _results_for(self, session: Session, run_id: UUID) -> list[ScenarioRunResult]:
        payloads = session.scalars(
            select(ScenarioResultRow.payload)
            .where(ScenarioResultRow.run_id == run_id)
            .order_by(ScenarioResultRow.position)
        )
        return [self._load_result(payload) for payload in payloads]

    def _record_from_row(
        self,
        row: TestRunRow,
        results: list[ScenarioRunResult],
    ) -> StoredTestRun:
        return StoredTestRun(
            run_id=row.run_id,
            pack=self._load_pack(row.pack_snapshot),
            agent_target=AgentTarget(row.agent_target),
            agent_mode=AgentMode(row.agent_mode),
            agent_label=row.agent_label,
            agent_version=row.agent_version,
            lifecycle_status=TestRunLifecycleStatus(row.lifecycle_status),
            created_at=_require_utc(row.created_at),
            started_at=_as_utc(row.started_at),
            completed_at=_as_utc(row.completed_at),
            results=results,
            error=self._load_error(row.error),
        )

    @staticmethod
    def _load_pack(payload: dict[str, Any]) -> ScenarioPackSummary:
        try:
            return ScenarioPackSummary.model_validate(payload)
        except ValidationError as error:
            raise CorruptedRunRecordError(
                "Stored scenario pack snapshot does not match the current schema."
            ) from error

    @staticmethod
    def _load_result(payload: dict[str, Any]) -> ScenarioRunResult:
        try:
            return ScenarioRunResult.model_validate(payload)
        except ValidationError as error:
            raise CorruptedRunRecordError(
                "Stored scenario result does not match the current schema."
            ) from error

    @staticmethod
    def _load_error(payload: dict[str, Any] | None) -> TestRunExecutionError | None:
        if payload is None:
            return None
        try:
            return TestRunExecutionError.model_validate(payload)
        except ValidationError as error:
            raise CorruptedRunRecordError(
                "Stored run error does not match the current schema."
            ) from error
