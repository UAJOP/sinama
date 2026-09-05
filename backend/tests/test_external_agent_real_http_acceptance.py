"""End-to-end acceptance proof over a real HTTP network boundary.

This module is intentionally different from `test_external_agent_boundaries.py`
and `test_http_agent.py`. Those drive the adapter through `httpx.MockTransport`,
which proves adapter contracts quickly but never serializes a request onto a
socket: the response object is handed back in-process.

Here every external-agent request is written to a real TCP connection, parsed by
an independent `http.server` process-local daemon, and read back over the wire.
That covers the one layer MockTransport cannot reach:

    real TCP/HTTP server -> HttpAgentAdapter -> ScenarioRunner -> evaluator
    -> ScenarioRunResult -> RunStore -> regression -> Release Readiness

Security note. The production SSRF policy is *not* relaxed. Every request still
goes through the real `validate_external_agent_endpoint`, which still requires a
globally routable destination and still rejects loopback. The single test-only
seam is `LoopbackRoutedTransport`, injected through the `transport` field that
`HttpAgentAdapter` already exposes and that `build_http_agent_adapter` never
sets. It changes which socket the real connection is dialled against; it does not
change what the policy accepts. `test_production_policy_still_rejects_the_
acceptance_server` pins that the acceptance server's own address is still
refused by the production path.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.evaluator import EvaluationCategory, EvaluationCheckType
from app.http_agent import (
    ExternalAgentConfiguration,
    HttpAgentAdapter,
    UnsafeAgentEndpointError,
    validate_external_agent_endpoint,
)
from app.models import AgentMode, AgentTarget
from app.readiness import (
    ReadinessReasonCode,
    ReadinessReasonLevel,
    ReleaseReadinessVerdict,
    build_release_readiness,
)
from app.regression import REGRESSION_THRESHOLD, ComparisonAvailability, RegressionStatus
from app.scenario_runner import (
    ExecutionErrorCategory,
    RunStatus,
    ScenarioRunner,
    ScenarioRunResult,
)
from app.scenarios import Severity, load_scenario_by_id
from app.test_runs import (
    InMemoryRunStore,
    RunService,
)
from app.test_runs import (
    TestRunLifecycleStatus as LifecycleStatus,
)
from tests.acceptance_agent_service import BehaviourVersion, running_demo_agent

COLLECTION_ID = "ecommerce-v1"
# A public hostname, so the production policy performs its normal DNS + pinning
# work. The address below is globally routable and satisfies the same is_global
# check production traffic does; no packet ever reaches it.
ACCEPTANCE_ENDPOINT = "http://agent.acceptance.example/turn"
PUBLIC_ADDRESS = "93.184.216.34"
BEARER = "acceptance-run-only-secret"

# ECOM-001 and ECOM-004 both declare "lookup_order before refund_order".
REFUND_SCENARIOS = ("ECOM-001", "ECOM-004")
# ECOM-002 (not-found) and ECOM-003 (escalation) never refund, so the injected
# defect must leave them untouched.
UNAFFECTED_SCENARIOS = ("ECOM-002", "ECOM-003")


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    """Deterministic DNS stand-in returning a globally routable address.

    Using a fixed address keeps the test hermetic (CI needs no DNS and no
    internet) while leaving the production `is_global` gate fully in force.
    """

    return (PUBLIC_ADDRESS,)


class LoopbackRoutedTransport(httpx.AsyncBaseTransport):
    """Real HTTP transport that dials the acceptance server's loopback socket.

    This is the only test-only seam in the acceptance path. It wraps a genuine
    `httpx.AsyncHTTPTransport`, so the request really is serialized, written to a
    TCP socket, and parsed back from the wire.

    `aclose` is deliberately inert: `HttpAgentAdapter` opens one `AsyncClient` per
    turn and closing that client would otherwise dispose of the shared inner
    transport before the next turn of the same scenario.
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self._port)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        return None

    async def shutdown(self) -> None:
        await self._inner.aclose()


@dataclass(frozen=True)
class ExecutedRun:
    run_id: UUID
    version: BehaviourVersion
    results: list[ScenarioRunResult]
    requests_received: int


async def _execute_collection(
    store: InMemoryRunStore,
    version: BehaviourVersion,
) -> ExecutedRun:
    """Run ecommerce-v1 against a live demo agent using real application logic."""

    with running_demo_agent(version) as agent:
        transport = LoopbackRoutedTransport(agent.port)

        def factory(configuration: ExternalAgentConfiguration) -> HttpAgentAdapter:
            return HttpAgentAdapter(
                endpoint_url=configuration.endpoint_url,
                bearer_token=configuration.bearer_token,
                timeout_seconds=4.0,
                max_response_bytes=262_144,
                production=False,
                resolver=public_resolver,
                transport=transport,
            )

        service = RunService(store=store, http_adapter_factory=factory)
        try:
            summary = await service.create_run(
                COLLECTION_ID,
                AgentMode.HEALTHY,
                agent_target=AgentTarget.EXTERNAL_HTTP,
                external_agent=ExternalAgentConfiguration(
                    endpoint_url=ACCEPTANCE_ENDPOINT,
                    bearer_token=SecretStr(BEARER),
                ),
                agent_version=version.value,
            )
            await service.wait_for_completion(summary.run_id)
        finally:
            await transport.shutdown()

        return ExecutedRun(
            run_id=summary.run_id,
            version=version,
            results=_full_results(store, summary.run_id),
            requests_received=len(agent.brain.received_messages),
        )


def _full_results(store: InMemoryRunStore, run_id: UUID) -> list[ScenarioRunResult]:
    """Fetch complete results; get_results() only returns display summaries."""

    return [
        store.get_result(run_id, summary.scenario_id)
        for summary in store.get_results(run_id).results
    ]


def _result(run: ExecutedRun, scenario_id: str) -> ScenarioRunResult:
    return next(item for item in run.results if item.scenario_id == scenario_id)


def _diagnostic(run: ExecutedRun, scenario_id: str) -> str:
    """Readable failure context. Never includes the bearer token."""

    result = _result(run, scenario_id)
    lines = [
        "",
        f"  behaviour version : {run.version.value}",
        f"  scenario          : {result.scenario_id} v{result.scenario_version}",
        f"  status / severity : {result.status.value} / "
        f"{result.severity.value if result.severity else '-'}",
        f"  turns executed    : {result.turns_executed}",
        f"  tool trace        : {[event.tool for event in result.tool_trace]}",
    ]
    for check in result.checks:
        lines.append(
            f"  check             : {check.check_id} -> {check.status.value}"
            f"{'' if check.category is None else ' (' + check.category.value + ')'}"
        )
    for failure in result.failures:
        lines.append(
            f"  failure           : {failure.type.value} [{failure.severity.value}] "
            f"turn={failure.turn} expected={failure.expected!r} actual={failure.actual!r}"
        )
    if result.error is not None:
        lines.append(f"  execution error   : {result.error.category.value} {result.error.reason}")
    return "\n".join(lines)


# --- Step 7: healthy path over a real socket -------------------------------------


def test_healthy_external_agent_passes_over_a_real_http_socket() -> None:
    store = InMemoryRunStore(max_runs=10)
    run = asyncio.run(_execute_collection(store, BehaviourVersion.HEALTHY))

    summary = store.get_run(run.run_id)
    assert summary.lifecycle_status is LifecycleStatus.COMPLETED
    assert summary.agent_target is AgentTarget.EXTERNAL_HTTP
    assert summary.agent_version == "healthy-v1"

    # The agent really was contacted: one HTTP request per scripted user turn.
    assert run.requests_received == 9, f"unexpected request count: {run.requests_received}"

    assert len(run.results) == 4
    for result in run.results:
        assert result.error is None, _diagnostic(run, result.scenario_id)
        assert result.status is RunStatus.PASS, _diagnostic(run, result.scenario_id)
        assert result.failures == [], _diagnostic(run, result.scenario_id)

    # Transcript and structured tool arguments survived JSON serialization.
    ecom_001 = _result(run, "ECOM-001")
    assert [turn.role.value for turn in ecom_001.transcript] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [event.tool for event in ecom_001.tool_trace] == ["lookup_order", "refund_order"]
    lookup = ecom_001.tool_trace[0]
    assert lookup.arguments == {
        "order_id": "ORD-DEMO-1001",
        "found": True,
        "return_eligible": True,
    }, "structured argument types must survive the HTTP boundary"


def test_conversation_id_is_stable_across_real_http_turns() -> None:
    store = InMemoryRunStore(max_runs=10)
    with running_demo_agent(BehaviourVersion.HEALTHY) as agent:
        transport = LoopbackRoutedTransport(agent.port)

        def factory(configuration: ExternalAgentConfiguration) -> HttpAgentAdapter:
            return HttpAgentAdapter(
                endpoint_url=configuration.endpoint_url,
                bearer_token=configuration.bearer_token,
                timeout_seconds=4.0,
                max_response_bytes=262_144,
                production=False,
                resolver=public_resolver,
                transport=transport,
            )

        async def execute() -> None:
            service = RunService(store=store, http_adapter_factory=factory)
            summary = await service.create_run(
                COLLECTION_ID,
                AgentMode.HEALTHY,
                agent_target=AgentTarget.EXTERNAL_HTTP,
                external_agent=ExternalAgentConfiguration(endpoint_url=ACCEPTANCE_ENDPOINT),
                agent_version="healthy-v1",
            )
            await service.wait_for_completion(summary.run_id)
            await transport.shutdown()

        asyncio.run(execute())
        received = list(agent.brain.received_messages)

    # Each scenario is one conversation; turns inside it share a conversation id.
    conversation_ids = [conversation_id for conversation_id, _ in received]
    assert len(set(conversation_ids)) == 4, "one stable conversation id per scenario"
    assert conversation_ids == sorted(conversation_ids, key=conversation_ids.index), (
        "turns of a conversation must not interleave"
    )


# --- Step 8: regressed path stays reachable but fails evaluation ------------------


def test_regressed_external_agent_is_reachable_but_fails_evaluation() -> None:
    store = InMemoryRunStore(max_runs=10)
    run = asyncio.run(_execute_collection(store, BehaviourVersion.REGRESSED))

    assert store.get_run(run.run_id).lifecycle_status is LifecycleStatus.COMPLETED
    assert run.requests_received == 9

    for scenario_id in REFUND_SCENARIOS:
        result = _result(run, scenario_id)
        context = _diagnostic(run, scenario_id)

        # Reachability is not the same as reliability: the HTTP call succeeded.
        assert result.error is None, context
        assert result.turns_executed > 0, context
        assert result.status is RunStatus.FAIL, context

        precondition_failures = [
            failure
            for failure in result.failures
            if failure.type is EvaluationCheckType.TOOL_PRECONDITION
        ]
        assert precondition_failures, context
        failure = precondition_failures[0]
        assert failure.severity is Severity.HIGH, context
        assert "lookup_order" in failure.expected, context
        assert "refund_order" in failure.actual or "refund_order" in failure.description, context

        # The offending event is identified in the evaluator evidence.
        offending = [
            check.evidence.offending_event
            for check in result.checks
            if check.evidence.offending_event is not None
        ]
        assert any(event.tool == "refund_order" for event in offending), context

        # The tool trace itself carries the violation.
        trace = [event.tool for event in result.tool_trace]
        assert trace.index("refund_order") < trace.index("lookup_order"), context

    # The defect is targeted, not a blanket outage.
    for scenario_id in UNAFFECTED_SCENARIOS:
        result = _result(run, scenario_id)
        assert result.status is RunStatus.PASS, _diagnostic(run, scenario_id)


def test_regressed_failure_evidence_names_the_violated_contract() -> None:
    store = InMemoryRunStore(max_runs=10)
    run = asyncio.run(_execute_collection(store, BehaviourVersion.REGRESSED))

    result = _result(run, "ECOM-001")
    context = _diagnostic(run, "ECOM-001")
    check = next(
        item
        for item in result.checks
        if item.type is EvaluationCheckType.TOOL_PRECONDITION
        and item.category is EvaluationCategory.TOOL_PRECONDITION_VIOLATION
    )
    assert check.evidence.prerequisite_tool == "lookup_order", context
    assert check.evidence.expected_tool == "refund_order", context
    assert check.evidence.offending_event is not None, context
    assert check.evidence.offending_event.arguments["order_id"] == "ORD-DEMO-1001", context


# --- Steps 9 and 10: baseline, regression and readiness --------------------------


def _healthy_baseline_then_regression() -> tuple[InMemoryRunStore, ExecutedRun, ExecutedRun]:
    store = InMemoryRunStore(max_runs=10)
    healthy = asyncio.run(_execute_collection(store, BehaviourVersion.HEALTHY))
    store.set_baseline(healthy.run_id)
    regressed = asyncio.run(_execute_collection(store, BehaviourVersion.REGRESSED))
    return store, healthy, regressed


def test_baseline_comparison_identifies_the_new_failures() -> None:
    store, healthy, regressed = _healthy_baseline_then_regression()

    response = store.get_comparison(regressed.run_id)
    assert response.status is ComparisonAvailability.AVAILABLE
    comparison = response.comparison
    assert comparison is not None
    assert comparison.baseline_run_id == healthy.run_id
    assert comparison.pack_id == COLLECTION_ID

    # The healthy run scored a clean 100; the regressed run drops on the two
    # scenarios whose refund contract the defect violates.
    assert comparison.baseline_score == 100
    assert comparison.current_score < comparison.baseline_score
    assert comparison.score_delta == -4

    new_failure_scenarios = {item.scenario_id for item in comparison.new_failures}
    assert new_failure_scenarios == set(REFUND_SCENARIOS), (
        f"unexpected new failures: {new_failure_scenarios}"
    )
    assert all(
        item.failure.type is EvaluationCheckType.TOOL_PRECONDITION
        for item in comparison.new_failures
    )
    assert all(item.failure.severity is Severity.HIGH for item in comparison.new_failures)
    assert comparison.resolved_failures == []


def test_aggregate_regression_label_stays_stable_below_the_score_threshold() -> None:
    """Pins existing policy: the aggregate label and the readiness verdict diverge.

    Two new high-severity failures appear and Release Readiness blocks the run, yet
    `RegressionStatus` is STABLE. That is what the current rules say:
    `compute_regression_status` escalates only on a new *critical* failure or a
    score move of at least REGRESSION_THRESHOLD (5), and this defect costs 4 points.

    This test documents the behaviour rather than changing it - regression and
    readiness policy are out of scope here. It is deliberately written so that
    tightening the rule later fails this test and forces a conscious decision.
    """

    store, _healthy, regressed = _healthy_baseline_then_regression()
    comparison = store.get_comparison(regressed.run_id).comparison
    assert comparison is not None

    assert REGRESSION_THRESHOLD == 5
    assert comparison.score_delta > -REGRESSION_THRESHOLD
    assert not any(item.failure.severity is Severity.CRITICAL for item in comparison.new_failures)
    assert comparison.status is RegressionStatus.STABLE

    # The failure evidence is still fully present; only the rolled-up label is soft.
    assert len(comparison.new_failures) == 2


def test_release_readiness_blocks_the_regressed_run() -> None:
    store, _healthy, regressed = _healthy_baseline_then_regression()

    readiness = build_release_readiness(
        store.get_run(regressed.run_id),
        _full_results(store, regressed.run_id),
        store.get_comparison(regressed.run_id),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.BLOCKED
    assert readiness.comparison_status is ComparisonAvailability.AVAILABLE

    blockers = [
        reason for reason in readiness.reasons if reason.level is ReadinessReasonLevel.BLOCKER
    ]
    assert blockers, readiness.model_dump_json(indent=2)

    high_failures = [
        reason for reason in blockers if reason.code is ReadinessReasonCode.HIGH_FAILURE
    ]
    assert {reason.scenario_id for reason in high_failures} == set(REFUND_SCENARIOS)
    for reason in high_failures:
        assert reason.failure_type is EvaluationCheckType.TOOL_PRECONDITION
        assert reason.failure_severity is Severity.HIGH
        assert reason.detail

    # The block comes from the absolute deterministic evidence, not the regression
    # label: see test_aggregate_regression_label_stays_stable_below_the_score_threshold.
    assert readiness.regression_status is RegressionStatus.STABLE
    assert not any(
        reason.code is ReadinessReasonCode.REGRESSION_DETECTED for reason in readiness.reasons
    )


def test_healthy_baseline_run_is_ready() -> None:
    store = InMemoryRunStore(max_runs=10)
    healthy = asyncio.run(_execute_collection(store, BehaviourVersion.HEALTHY))
    store.set_baseline(healthy.run_id)

    readiness = build_release_readiness(
        store.get_run(healthy.run_id),
        _full_results(store, healthy.run_id),
        store.get_comparison(healthy.run_id),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.READY, readiness.model_dump_json(indent=2)
    assert readiness.comparison_status is ComparisonAvailability.IS_BASELINE


# --- The seam must not have widened the production policy ------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8080/turn",
        "http://localhost:8080/turn",
        "http://[::1]:8080/turn",
    ],
)
def test_production_policy_still_rejects_the_acceptance_server(endpoint: str) -> None:
    """The acceptance server's own address stays unreachable to production."""

    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(validate_external_agent_endpoint(endpoint, production=False))


def test_acceptance_endpoint_is_only_reachable_through_the_injected_transport() -> None:
    """Without the test transport, nothing dials the loopback acceptance server.

    The endpoint the acceptance run uses is validated to a *public* address. Real
    traffic would be pinned there, which is exactly why the loopback redirect has
    to be supplied explicitly at construction and can never come from config.
    """

    destination = asyncio.run(
        validate_external_agent_endpoint(
            ACCEPTANCE_ENDPOINT,
            production=False,
            resolver=public_resolver,
        )
    )

    assert destination.request_url.host == PUBLIC_ADDRESS
    assert destination.host_header == "agent.acceptance.example"
    assert "127.0.0.1" not in str(destination.request_url)


def test_the_boundary_is_genuinely_networked() -> None:
    """Stopping the server must break the run.

    This is the control for the whole module. A MockTransport-style seam would be
    indifferent to whether anything is listening; a real socket is not. The port
    is captured while the server runs and used after it has been shut down, so the
    adapter dials a closed port and reports a contained adapter error.
    """

    with running_demo_agent(BehaviourVersion.HEALTHY) as agent:
        closed_port = agent.port
    # The context manager has now shut the listener down.

    transport = LoopbackRoutedTransport(closed_port)
    adapter = HttpAgentAdapter(
        endpoint_url=ACCEPTANCE_ENDPOINT,
        timeout_seconds=4.0,
        max_response_bytes=262_144,
        production=False,
        resolver=public_resolver,
        transport=transport,
    )

    async def execute() -> ScenarioRunResult:
        try:
            return await ScenarioRunner().run(load_scenario_by_id("ECOM-001"), adapter)
        finally:
            await transport.shutdown()

    result = asyncio.run(execute())

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.ADAPTER_ERROR
    assert result.tool_trace == []
    # The sanitized message must not leak connection internals.
    assert "127.0.0.1" not in result.error.reason
