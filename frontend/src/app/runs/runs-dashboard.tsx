"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createTestRun,
  getRunComparison,
  getScenarioRunResult,
  getTestRun,
  getTestRunResults,
  listScenarioPacks,
  setRunBaseline,
  testExternalAgentConnection,
  type AgentMode,
  type AgentTarget,
  type ConnectionTestStatus,
  type EvaluationCheck,
  type Failure,
  type JsonScalar,
  type MetricComparison,
  type MetricDimension,
  type MetricScore,
  type MetricStatus,
  type RegressionComparison,
  type RegressionComparisonResponse,
  type RegressionStatus,
  type RunLifecycleStatus,
  type ScenarioCategory,
  type ScenarioFailure,
  type ScenarioPack,
  type ScenarioResultSummary,
  type ScenarioRunResult,
  type ScenarioRunStatus,
  type Severity,
  type TestRunSummary,
  type ToolEvent,
} from "@/lib/api";

import styles from "./runs.module.css";

type DetailTab = "checks" | "metrics" | "failures" | "transcript" | "trace" | "coverage";
type ConnectionState = "idle" | "testing" | ConnectionTestStatus;
type FailureFilter = "all" | Severity;
type RunView = "results" | "regression";

const TARGET_OPTIONS: { value: AgentTarget; label: string; note: string }[] = [
  {
    value: "built_in_demo",
    label: "Built-in Demo Agent",
    note: "Deterministic local baseline",
  },
  {
    value: "external_http",
    label: "External HTTP Agent",
    note: "Your secured turn endpoint",
  },
];

const MODE_OPTIONS: { value: AgentMode; label: string; note: string }[] = [
  { value: "healthy", label: "Healthy", note: "Expected safe behavior" },
  {
    value: "broken_premature_submission",
    label: "Broken: Premature Submission",
    note: "Known regression target",
  },
];

const LIFECYCLE_LABELS: Record<RunLifecycleStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  error: "Execution error",
};

const STATUS_LABELS: Record<ScenarioRunStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  error: "Error",
};

const CATEGORY_LABELS: Record<ScenarioCategory, string> = {
  tool_call_policy: "Tool call policy",
  coverage_safety: "Coverage safety",
  privacy: "Privacy",
  human_handoff: "Human handoff",
  prompt_injection: "Prompt injection",
  context_retention: "Context retention",
  ambiguous_intent: "Ambiguous intent",
  turkish_noise: "Turkish noise",
  repeated_request: "Repeated request",
  failed_tool_recovery: "Failed tool recovery",
};

const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const TAB_LABELS: Record<DetailTab, string> = {
  checks: "Checks",
  metrics: "Metrics",
  failures: "Failures",
  transcript: "Transcript",
  trace: "Tool Trace",
  coverage: "Coverage",
};

const METRIC_LABELS: Record<MetricDimension, string> = {
  goal_completion: "Goal Completion",
  tool_usage: "Tool Usage",
  handoff: "Handoff",
  safety: "Safety",
  conversation_quality: "Conversation Quality",
};

const METRIC_STATUS_LABELS: Record<MetricStatus, string> = {
  pass: "Pass",
  warning: "Warning",
  fail: "Fail",
  not_applicable: "N/A",
};

const FAILURE_FILTERS: FailureFilter[] = ["all", "critical", "high", "medium", "low"];

const REGRESSION_STATUS_LABELS: Record<RegressionStatus, string> = {
  improved: "Improved",
  stable: "Stable",
  regression: "Regression",
};

const RUN_VIEW_LABELS: Record<RunView, string> = {
  results: "Scenario Results",
  regression: "Regression",
};

const TERMINAL_STATUSES: RunLifecycleStatus[] = ["completed", "error"];
const POLL_DELAY_MS = 350;
const MAX_POLL_FAILURES = 4;

function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function displayValue(value: JsonScalar | JsonScalar[] | undefined): string {
  if (value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function eventTime(timestamp: string): string {
  return new Intl.DateTimeFormat("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

function resultSelection(results: ScenarioResultSummary[]): string | null {
  return results.find((item) => item.status === "fail")?.scenario_id ?? results[0]?.scenario_id ?? null;
}

export function RunsDashboard() {
  const [packs, setPacks] = useState<ScenarioPack[]>([]);
  const [packsLoading, setPacksLoading] = useState(true);
  const [packsError, setPacksError] = useState<string | null>(null);
  const [packsReload, setPacksReload] = useState(0);
  const [pollRetry, setPollRetry] = useState(0);
  const [selectedPackId, setSelectedPackId] = useState("");
  const [selectedMode, setSelectedMode] = useState<AgentMode>("healthy");
  const [agentTarget, setAgentTarget] = useState<AgentTarget>("built_in_demo");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [bearerToken, setBearerToken] = useState("");
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null);

  const [run, setRun] = useState<TestRunSummary | null>(null);
  const [results, setResults] = useState<ScenarioResultSummary[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScenarioRunResult | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("checks");
  const [isCreating, setIsCreating] = useState(false);
  const [isLoadingResults, setIsLoadingResults] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [runView, setRunView] = useState<RunView>("results");
  const [comparisonResponse, setComparisonResponse] = useState<RegressionComparisonResponse | null>(
    null,
  );
  const [isLoadingComparison, setIsLoadingComparison] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [comparisonReload, setComparisonReload] = useState(0);
  const [isSettingBaseline, setIsSettingBaseline] = useState(false);
  const [baselineError, setBaselineError] = useState<string | null>(null);

  const createSerial = useRef(0);
  const pollSerial = useRef(0);
  const resultsSerial = useRef(0);
  const detailSerial = useRef(0);
  const connectionSerial = useRef(0);
  const comparisonSerial = useRef(0);

  useEffect(() => {
    const controller = new AbortController();

    void listScenarioPacks(controller.signal)
      .then((payload) => {
        setPacks(payload);
        setSelectedPackId((current) => current || payload[0]?.id || "");
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) {
          setPacksError(errorMessage(cause, "Scenario packs could not be loaded."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setPacksLoading(false);
      });

    return () => controller.abort();
  }, [packsReload]);

  const selectedPack = useMemo(
    () => packs.find((pack) => pack.id === selectedPackId) ?? null,
    [packs, selectedPackId],
  );

  const runIsActive = run !== null && !TERMINAL_STATUSES.includes(run.lifecycle_status);
  const terminalRunId =
    run && TERMINAL_STATUSES.includes(run.lifecycle_status) ? run.run_id : null;
  const activeRunId = run?.run_id ?? null;
  const externalConnectionReady =
    agentTarget === "built_in_demo" || connectionState === "success";

  const resetConnectionFeedback = useCallback(() => {
    ++connectionSerial.current;
    setConnectionState("idle");
    setConnectionMessage(null);
  }, []);

  const handleTestConnection = useCallback(async () => {
    const normalizedEndpoint = endpointUrl.trim();
    if (!normalizedEndpoint || connectionState === "testing" || runIsActive) return;

    const serial = ++connectionSerial.current;
    setConnectionState("testing");
    setConnectionMessage("Testing the external turn contract…");

    try {
      const result = await testExternalAgentConnection({
        endpoint_url: normalizedEndpoint,
        ...(bearerToken ? { bearer_token: bearerToken } : {}),
      });
      if (serial !== connectionSerial.current) return;
      setConnectionState(result.status);
      setConnectionMessage(
        result.http_status_code
          ? `${result.message} HTTP ${result.http_status_code}.`
          : result.message,
      );
    } catch (cause) {
      if (serial !== connectionSerial.current) return;
      setConnectionState("network_error");
      setConnectionMessage(errorMessage(cause, "Connection test could not be completed."));
    }
  }, [bearerToken, connectionState, endpointUrl, runIsActive]);

  const handleCreateRun = useCallback(async () => {
    if (!selectedPackId || isCreating || runIsActive || !externalConnectionReady) return;
    const serial = ++createSerial.current;
    ++pollSerial.current;
    ++resultsSerial.current;
    ++detailSerial.current;
    setIsCreating(true);
    setRunError(null);
    setDetailError(null);
    setRun(null);
    setResults([]);
    setSelectedScenarioId(null);
    setDetail(null);
    setActiveTab("checks");
    setRunView("results");
    setBaselineError(null);
    setComparisonResponse(null);
    setComparisonError(null);
    ++comparisonSerial.current;

    try {
      const created = await createTestRun(
        selectedPackId,
        selectedMode,
        agentTarget,
        agentTarget === "external_http"
          ? {
              endpoint_url: endpointUrl.trim(),
              ...(bearerToken ? { bearer_token: bearerToken } : {}),
            }
          : undefined,
      );
      if (serial !== createSerial.current) return;
      setRun(created);
      if (agentTarget === "external_http") {
        setBearerToken("");
        setConnectionState("idle");
        setConnectionMessage("Connection credentials cleared after the run was accepted.");
      }
    } catch (cause) {
      if (serial !== createSerial.current) return;
      setRunError(errorMessage(cause, "Test run could not be created."));
    } finally {
      if (serial === createSerial.current) setIsCreating(false);
    }
  }, [
    agentTarget,
    bearerToken,
    endpointUrl,
    externalConnectionReady,
    isCreating,
    runIsActive,
    selectedMode,
    selectedPackId,
  ]);

  const handleSetBaseline = useCallback(async () => {
    if (!run || run.lifecycle_status !== "completed" || isSettingBaseline) return;
    setIsSettingBaseline(true);
    setBaselineError(null);
    try {
      const updated = await setRunBaseline(run.run_id);
      setRun(updated);
      setIsLoadingComparison(true);
      setComparisonError(null);
      setComparisonReload((value) => value + 1);
    } catch (cause) {
      setBaselineError(errorMessage(cause, "This run could not be set as the baseline."));
    } finally {
      setIsSettingBaseline(false);
    }
  }, [isSettingBaseline, run]);

  useEffect(() => {
    if (!run || TERMINAL_STATUSES.includes(run.lifecycle_status)) return;

    const serial = ++pollSerial.current;
    const controller = new AbortController();
    let timer: number | undefined;
    let consecutiveFailures = 0;

    const poll = async () => {
      try {
        const current = await getTestRun(run.run_id, controller.signal);
        if (serial !== pollSerial.current || controller.signal.aborted) return;
        consecutiveFailures = 0;
        if (TERMINAL_STATUSES.includes(current.lifecycle_status)) {
          setIsLoadingResults(true);
          setIsLoadingComparison(true);
          setComparisonError(null);
        }
        setRun(current);
        if (!TERMINAL_STATUSES.includes(current.lifecycle_status)) {
          timer = window.setTimeout(() => void poll(), POLL_DELAY_MS);
        }
      } catch (cause) {
        if (isAbortError(cause) || serial !== pollSerial.current) return;
        consecutiveFailures += 1;
        if (consecutiveFailures <= MAX_POLL_FAILURES) {
          timer = window.setTimeout(() => void poll(), POLL_DELAY_MS * consecutiveFailures);
        } else {
          setRunError("Run status polling stopped after repeated connection failures. Retry the run.");
        }
      }
    };

    timer = window.setTimeout(() => void poll(), 120);
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [pollRetry, run]);

  useEffect(() => {
    if (!terminalRunId) return;

    const serial = ++resultsSerial.current;
    const controller = new AbortController();

    void getTestRunResults(terminalRunId, controller.signal)
      .then((payload) => {
        if (serial !== resultsSerial.current) return;
        const defaultSelection = resultSelection(payload.results);
        setRun(payload.run);
        setResults(payload.results);
        setSelectedScenarioId(defaultSelection);
        setDetail(null);
        setDetailError(null);
        setIsLoadingDetail(defaultSelection !== null);
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause) && serial === resultsSerial.current) {
          setRunError(errorMessage(cause, "Run results could not be loaded."));
        }
      })
      .finally(() => {
        if (serial === resultsSerial.current) setIsLoadingResults(false);
      });

    return () => controller.abort();
  }, [terminalRunId]);

  useEffect(() => {
    if (!terminalRunId) return;

    const serial = ++comparisonSerial.current;
    const controller = new AbortController();

    void getRunComparison(terminalRunId, controller.signal)
      .then((payload) => {
        if (serial === comparisonSerial.current) setComparisonResponse(payload);
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause) && serial === comparisonSerial.current) {
          setComparisonError(errorMessage(cause, "Regression comparison could not be loaded."));
        }
      })
      .finally(() => {
        if (serial === comparisonSerial.current) setIsLoadingComparison(false);
      });

    return () => controller.abort();
  }, [terminalRunId, comparisonReload]);

  useEffect(() => {
    if (!activeRunId || !selectedScenarioId) return;

    const serial = ++detailSerial.current;
    const controller = new AbortController();

    void getScenarioRunResult(activeRunId, selectedScenarioId, controller.signal)
      .then((payload) => {
        if (serial === detailSerial.current) setDetail(payload);
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause) && serial === detailSerial.current) {
          setDetailError(errorMessage(cause, "Scenario detail could not be loaded."));
        }
      })
      .finally(() => {
        if (serial === detailSerial.current) setIsLoadingDetail(false);
      });

    return () => controller.abort();
  }, [activeRunId, selectedScenarioId]);

  const progressPercent = run
    ? Math.round((run.completed_scenarios / run.total_scenarios) * 100)
    : 0;

  return (
    <main className={styles.shell}>
      <header className={styles.pageHeader}>
        <div>
          <p className="eyebrow">AUTOMATED EVALUATION</p>
          <h1>Test Runs</h1>
          <p>Run the insurance pack against a built-in or external agent and inspect the same deterministic evidence.</p>
        </div>
        <span className={styles.storageNote}>IN-MEMORY · LAST 20 RUNS</span>
      </header>

      <section className={styles.runControls} aria-labelledby="run-controls-title">
        <div className={styles.controlIntro}>
          <span className={styles.stepNumber}>01</span>
          <div>
            <h2 id="run-controls-title">Configure run</h2>
            <p>The selected mode applies only to the next run.</p>
          </div>
        </div>

        {packsError ? (
          <div className={styles.inlineError} role="alert">
            <span>{packsError}</span>
            <button
              type="button"
              onClick={() => {
                setPacksLoading(true);
                setPacksError(null);
                setPacksReload((value) => value + 1);
              }}
            >
              Retry
            </button>
          </div>
        ) : (
          <div className={styles.controlFields}>
            <label>
              <span>Scenario pack</span>
              <select
                value={selectedPackId}
                onChange={(event) => setSelectedPackId(event.target.value)}
                disabled={packsLoading || isCreating || runIsActive}
              >
                {packsLoading && <option>Loading packs…</option>}
                {packs.map((pack) => (
                  <option value={pack.id} key={pack.id}>
                    {pack.name} · {pack.scenario_count} scenarios
                  </option>
                ))}
              </select>
            </label>

            <fieldset className={styles.modeField} disabled={isCreating || runIsActive}>
              <legend>Agent target</legend>
              <div className={styles.modeOptions}>
                {TARGET_OPTIONS.map((option) => (
                  <label className={agentTarget === option.value ? styles.modeSelected : ""} key={option.value}>
                    <input
                      type="radio"
                      name="agent-target"
                      value={option.value}
                      checked={agentTarget === option.value}
                      onChange={() => {
                        setAgentTarget(option.value);
                        if (option.value === "built_in_demo") setBearerToken("");
                        resetConnectionFeedback();
                      }}
                    />
                    <span><strong>{option.label}</strong><small>{option.note}</small></span>
                  </label>
                ))}
              </div>
            </fieldset>

            <button
              className={styles.runButton}
              type="button"
              onClick={() => void handleCreateRun()}
              disabled={
                !selectedPackId ||
                packsLoading ||
                isCreating ||
                runIsActive ||
                !externalConnectionReady
              }
            >
              {isCreating ? "Starting…" : runIsActive ? "Run in progress" : "Run Test Pack"}
              <span aria-hidden="true">↗</span>
            </button>

            <div className={styles.agentConfiguration}>
              {agentTarget === "built_in_demo" ? (
                <fieldset className={styles.modeField} disabled={isCreating || runIsActive}>
                  <legend>Agent mode</legend>
                  <div className={styles.modeOptions}>
                    {MODE_OPTIONS.map((option) => (
                      <label className={selectedMode === option.value ? styles.modeSelected : ""} key={option.value}>
                        <input
                          type="radio"
                          name="run-mode"
                          value={option.value}
                          checked={selectedMode === option.value}
                          onChange={() => setSelectedMode(option.value)}
                        />
                        <span><strong>{option.label}</strong><small>{option.note}</small></span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <div className={styles.externalConfiguration}>
                  <label>
                    <span>Endpoint URL</span>
                    <input
                      type="url"
                      inputMode="url"
                      placeholder="https://agent.example.com/turn"
                      value={endpointUrl}
                      onChange={(event) => {
                        setEndpointUrl(event.target.value);
                        resetConnectionFeedback();
                      }}
                      disabled={isCreating || runIsActive}
                      required
                    />
                  </label>
                  <label>
                    <span>Optional bearer token</span>
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder="Not stored"
                      value={bearerToken}
                      onChange={(event) => {
                        setBearerToken(event.target.value);
                        resetConnectionFeedback();
                      }}
                      disabled={isCreating || runIsActive}
                    />
                  </label>
                  <button
                    className={styles.connectionButton}
                    type="button"
                    onClick={() => void handleTestConnection()}
                    disabled={
                      !endpointUrl.trim() ||
                      connectionState === "testing" ||
                      isCreating ||
                      runIsActive
                    }
                  >
                    {connectionState === "testing" ? "Testing…" : "Test connection"}
                  </button>
                  {connectionMessage && (
                    <p
                      className={`${styles.connectionFeedback} ${
                        connectionState === "success"
                          ? styles.connectionSuccess
                          : connectionState === "idle" || connectionState === "testing"
                            ? ""
                            : styles.connectionFailure
                      }`}
                      role={
                        connectionState === "idle" ||
                        connectionState === "success" ||
                        connectionState === "testing"
                          ? "status"
                          : "alert"
                      }
                    >
                      {connectionMessage}
                    </p>
                  )}
                  <small>Bearer tokens stay only in this page&apos;s memory and are cleared after run creation.</small>
                </div>
              )}
            </div>
          </div>
        )}

        {selectedPack && !packsError && (
          <p className={styles.packDescription}>
            <strong>{selectedPack.id}</strong> · {selectedPack.description}
          </p>
        )}
      </section>

      {runError && (
        <div className={styles.errorBanner} role="alert">
          <div><strong>Run unavailable</strong><span>{runError}</span></div>
          <button
            type="button"
            onClick={() => {
              if (runIsActive) {
                setRunError(null);
                setPollRetry((value) => value + 1);
              } else {
                void handleCreateRun();
              }
            }}
            disabled={isCreating}
          >
            {runIsActive ? "Resume status" : "Retry run"}
          </button>
        </div>
      )}

      {!run ? (
        <EmptyRunState />
      ) : (
        <>
          <RunOverview
            run={run}
            progressPercent={progressPercent}
            comparisonResponse={comparisonResponse}
            onSetBaseline={() => void handleSetBaseline()}
            isSettingBaseline={isSettingBaseline}
            baselineError={baselineError}
          />
          {run.lifecycle_status === "error" && run.error && (
            <div className={styles.executionError} role="alert">
              <strong>{run.error.category}</strong>
              <span>{run.error.reason}</span>
            </div>
          )}

          {TERMINAL_STATUSES.includes(run.lifecycle_status) && (
            <div className={styles.viewToggle} role="tablist" aria-label="Run detail view">
              {(Object.keys(RUN_VIEW_LABELS) as RunView[]).map((view) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={runView === view}
                  className={runView === view ? styles.activeViewTab : ""}
                  key={view}
                  onClick={() => setRunView(view)}
                >
                  {RUN_VIEW_LABELS[view]}
                </button>
              ))}
            </div>
          )}

          {runView === "regression" ? (
            <RegressionView
              response={comparisonResponse}
              isLoading={isLoadingComparison}
              error={comparisonError}
            />
          ) : isLoadingResults ? (
            <LoadingBlock label="Loading scenario summaries…" />
          ) : results.length > 0 ? (
            <section className={styles.inspectionGrid} aria-label="Run results inspection">
              <ResultList
                results={results}
                selectedScenarioId={selectedScenarioId}
                onSelect={(scenarioId) => {
                  setSelectedScenarioId(scenarioId);
                  setDetail(null);
                  setDetailError(null);
                  setIsLoadingDetail(true);
                  setActiveTab("checks");
                }}
              />
              <ResultDetail
                summary={results.find((item) => item.scenario_id === selectedScenarioId) ?? null}
                detail={detail}
                isLoading={isLoadingDetail}
                error={detailError}
                activeTab={activeTab}
                onTabChange={setActiveTab}
              />
            </section>
          ) : TERMINAL_STATUSES.includes(run.lifecycle_status) ? (
            <div className={styles.noResults}>No scenario results were recorded for this run.</div>
          ) : null}
        </>
      )}
    </main>
  );
}

function EmptyRunState() {
  return (
    <section className={styles.emptyRun}>
      <div className={styles.heroFrame} aria-hidden="true">
        <Image src="/images/sinama-hero.png" alt="" width={688} height={384} priority />
      </div>
      <div>
        <span className={styles.stepNumber}>02</span>
        <p className="eyebrow">NO RUN SELECTED</p>
        <h2>Evidence begins with a run.</h2>
        <p>
          Choose the deterministic demo baseline or connect an external HTTP agent using the same
          scenario evidence workflow.
        </p>
        <ul className={styles.emptyFacts}>
          <li>10 synthetic Turkish scenarios</li>
          <li>Structured tool-contract evaluation</li>
          <li>No external API key required</li>
        </ul>
      </div>
    </section>
  );
}

function RunOverview({
  run,
  progressPercent,
  comparisonResponse,
  onSetBaseline,
  isSettingBaseline,
  baselineError,
}: {
  run: TestRunSummary;
  progressPercent: number;
  comparisonResponse: RegressionComparisonResponse | null;
  onSetBaseline: () => void;
  isSettingBaseline: boolean;
  baselineError: string | null;
}) {
  const aggregateCards = [
    { label: "Total", value: run.aggregate.total, tone: "neutral", icon: "Σ" },
    { label: "Passed", value: run.aggregate.passed, tone: "pass", icon: "✓" },
    { label: "Failed", value: run.aggregate.failed, tone: "fail", icon: "!" },
    { label: "Errors", value: run.aggregate.errors, tone: "error", icon: "×" },
  ] as const;

  const regressionBadge =
    run.is_baseline
      ? { label: "Baseline", status: "baseline" as const }
      : comparisonResponse?.status === "available" && comparisonResponse.comparison
        ? { label: REGRESSION_STATUS_LABELS[comparisonResponse.comparison.status], status: comparisonResponse.comparison.status }
        : null;

  return (
    <section className={styles.overview} aria-labelledby="run-overview-title">
      <div className={styles.runIdentity}>
        <div>
          <p className="eyebrow">RUN</p>
          <h2 id="run-overview-title">{run.pack_name}</h2>
          <code>{run.run_id}</code>
        </div>
        <div className={styles.overviewBadges}>
          {regressionBadge && (
            <span className={`${styles.regressionBadge} ${styles[regressionBadge.status]}`}>
              {regressionBadge.label}
            </span>
          )}
          <span className={`${styles.lifecycle} ${styles[run.lifecycle_status]}`}>
            <i aria-hidden="true" /> {LIFECYCLE_LABELS[run.lifecycle_status]}
          </span>
        </div>
      </div>

      <div className={styles.progressCopy}>
        <span>{run.completed_scenarios} / {run.total_scenarios} scenarios observed</span>
        <span>{progressPercent}%</span>
      </div>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={run.total_scenarios}
        aria-valuenow={run.completed_scenarios}
        aria-label="Run progress"
      >
        <span style={{ width: `${progressPercent}%` }} />
      </div>

      <div className={styles.aggregateGrid}>
        {aggregateCards.map((card) => (
          <div className={`${styles.aggregateCard} ${styles[card.tone]}`} key={card.label}>
            <span><i aria-hidden="true">{card.icon}</i>{card.label}</span>
            <strong>{card.value}</strong>
          </div>
        ))}
      </div>
      <div className={styles.runMeta}>
        <span>
          TARGET <strong>{run.agent_target === "external_http" ? "External HTTP" : "Built-in Demo"}</strong>
        </span>
        {run.agent_target === "built_in_demo" && (
          <span>MODE <strong>{run.agent_mode === "healthy" ? "Healthy" : "Broken"}</strong></span>
        )}
        <span>PACK <strong>{run.pack_id}</strong></span>
        <span>OUTCOMES <strong>Observed results only</strong></span>
        <span className={styles.baselineAction}>
          {run.is_baseline ? (
            <span className={styles.baselineState}>Baseline</span>
          ) : (
            <button
              type="button"
              className={styles.baselineButton}
              onClick={onSetBaseline}
              disabled={run.lifecycle_status !== "completed" || isSettingBaseline}
            >
              {isSettingBaseline ? "Setting…" : "Set as baseline"}
            </button>
          )}
        </span>
      </div>
      {baselineError && (
        <p className={styles.baselineError} role="alert">{baselineError}</p>
      )}
    </section>
  );
}

function ResultList({
  results,
  selectedScenarioId,
  onSelect,
}: {
  results: ScenarioResultSummary[];
  selectedScenarioId: string | null;
  onSelect: (scenarioId: string) => void;
}) {
  return (
    <aside className={styles.resultList} aria-label="Scenario results">
      <div className={styles.sectionHeader}>
        <div><p className="eyebrow">SCENARIOS</p><h2>Results</h2></div>
        <span>{results.length}</span>
      </div>
      <div className={styles.resultButtons}>
        {results.map((result) => (
          <button
            type="button"
            key={result.scenario_id}
            className={`${styles.resultButton} ${styles[result.status]} ${selectedScenarioId === result.scenario_id ? styles.resultSelected : ""}`}
            onClick={() => onSelect(result.scenario_id)}
            aria-pressed={selectedScenarioId === result.scenario_id}
          >
            <span className={styles.resultStatus} aria-hidden="true">
              {result.status === "pass" ? "✓" : result.status === "fail" ? "!" : "×"}
            </span>
            <span className={styles.resultText}>
              <span><strong>{result.scenario_id}</strong><small>{STATUS_LABELS[result.status]}</small></span>
              <b>{result.title}</b>
              <span className={styles.resultMeta}>
                {CATEGORY_LABELS[result.category]}
                {result.severity && <> · {SEVERITY_LABELS[result.severity]}</>}
                {result.failed_check_count > 0 && <> · {result.failed_check_count} failed</>}
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function ResultDetail({
  summary,
  detail,
  isLoading,
  error,
  activeTab,
  onTabChange,
}: {
  summary: ScenarioResultSummary | null;
  detail: ScenarioRunResult | null;
  isLoading: boolean;
  error: string | null;
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}) {
  if (!summary) return <section className={styles.resultDetail}>Select a scenario.</section>;

  return (
    <section className={styles.resultDetail} aria-labelledby="scenario-detail-title">
      <div className={styles.detailHeader}>
        <div>
          <p className="eyebrow">{CATEGORY_LABELS[summary.category]}</p>
          <h2 id="scenario-detail-title">{summary.scenario_id} · {summary.title}</h2>
        </div>
        <span className={`${styles.statusPill} ${styles[summary.status]}`}>
          {STATUS_LABELS[summary.status]}
          {summary.severity && ` · ${SEVERITY_LABELS[summary.severity]}`}
        </span>
      </div>

      <div className={styles.tabs} role="tablist" aria-label="Scenario evidence views">
        {(Object.keys(TAB_LABELS) as DetailTab[]).map((tab) => (
          <button
            type="button"
            role="tab"
            id={`tab-${tab}`}
            aria-controls={`panel-${tab}`}
            aria-selected={activeTab === tab}
            className={activeTab === tab ? styles.activeTab : ""}
            key={tab}
            onClick={() => onTabChange(tab)}
          >
            {TAB_LABELS[tab]}
            {detail && tab === "checks" && <span>{detail.checks.length}</span>}
            {detail && tab === "failures" && <span>{detail.failures.length}</span>}
          </button>
        ))}
      </div>

      <div
        className={styles.tabPanel}
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
      >
        {isLoading ? (
          <LoadingBlock label="Loading structured evidence…" />
        ) : error ? (
          <div className={styles.detailError} role="alert">{error}</div>
        ) : detail ? (
          <DetailTabContent activeTab={activeTab} detail={detail} />
        ) : null}
      </div>
    </section>
  );
}

function DetailTabContent({ activeTab, detail }: { activeTab: DetailTab; detail: ScenarioRunResult }) {
  if (activeTab === "checks") return <ChecksView checks={detail.checks} error={detail.error} />;
  if (activeTab === "metrics") return <MetricsView metrics={detail.metrics} />;
  if (activeTab === "failures") return <FailuresView failures={detail.failures} />;
  if (activeTab === "transcript") return <TranscriptView detail={detail} />;
  if (activeTab === "trace") return <ToolTraceView detail={detail} />;
  return <CoverageView detail={detail} />;
}

function MetricsView({ metrics }: { metrics: MetricScore[] }) {
  if (metrics.length === 0) return <p className={styles.emptyTab}>No metrics were computed.</p>;

  return (
    <div className={styles.metricGrid}>
      {metrics.map((metric) => (
        <article className={`${styles.metricCard} ${styles[metric.status]}`} key={metric.dimension}>
          <div className={styles.metricHead}>
            <h3>{METRIC_LABELS[metric.dimension]}</h3>
            <span className={styles.metricStatusTag}>{METRIC_STATUS_LABELS[metric.status]}</span>
          </div>
          <strong className={styles.metricScore}>{metric.score === null ? "—" : metric.score}</strong>
          <p>{metric.reason}</p>
        </article>
      ))}
    </div>
  );
}

function FailuresView({ failures }: { failures: Failure[] }) {
  const [filter, setFilter] = useState<FailureFilter>("all");
  const filtered = filter === "all" ? failures : failures.filter((failure) => failure.severity === filter);

  if (failures.length === 0) return <p className={styles.emptyTab}>No failures were recorded.</p>;

  return (
    <div>
      <div className={styles.failureFilters} role="tablist" aria-label="Filter failures by severity">
        {FAILURE_FILTERS.map((option) => (
          <button
            type="button"
            key={option}
            className={filter === option ? styles.activeFilter : ""}
            onClick={() => setFilter(option)}
            aria-pressed={filter === option}
          >
            {option === "all" ? "All" : SEVERITY_LABELS[option]}
          </button>
        ))}
      </div>
      {filtered.length === 0 ? (
        <p className={styles.emptyTab}>No failures at this severity.</p>
      ) : (
        <div className={styles.failureList}>
          {filtered.map((failure, index) => (
            <FailureCard failure={failure} key={index} />
          ))}
        </div>
      )}
    </div>
  );
}

function FailureCard({ failure, scenarioId }: { failure: Failure; scenarioId?: string }) {
  return (
    <article className={`${styles.failureCard} ${styles[failure.severity]}`}>
      <div className={styles.failureHeading}>
        <strong>{scenarioId ? `${scenarioId} · ${failure.title}` : failure.title}</strong>
        <span>{SEVERITY_LABELS[failure.severity]}</span>
      </div>
      {failure.turn !== null && <p className={styles.failureTurn}>Turn {failure.turn}</p>}
      <dl className={styles.failureGrid}>
        <dt>Expected</dt>
        <dd>{failure.expected}</dd>
        <dt>Actual</dt>
        <dd>{failure.actual}</dd>
        <dt>Suggestion</dt>
        <dd>{failure.suggestion}</dd>
      </dl>
    </article>
  );
}

function RegressionView({
  response,
  isLoading,
  error,
}: {
  response: RegressionComparisonResponse | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (isLoading) {
    return (
      <section className={styles.regressionSection}>
        <LoadingBlock label="Loading regression comparison…" />
      </section>
    );
  }
  if (error) {
    return (
      <section className={styles.regressionSection}>
        <div className={styles.detailError} role="alert">{error}</div>
      </section>
    );
  }
  if (!response || response.status === "no_baseline") {
    return (
      <section className={styles.regressionSection}>
        <div className={styles.regressionEmpty}>
          <p className="eyebrow">NO BASELINE SET</p>
          <h3>No baseline set</h3>
          <p>Set a completed run as baseline to compare future reliability changes.</p>
        </div>
      </section>
    );
  }
  if (response.status === "is_baseline") {
    return (
      <section className={styles.regressionSection}>
        <div className={styles.regressionEmpty}>
          <p className="eyebrow">BASELINE</p>
          <h3>This run is the current baseline.</h3>
          <p>Run the pack again after changing agent behavior to compare it against this run.</p>
        </div>
      </section>
    );
  }
  if (response.status === "incompatible" || !response.comparison) {
    return (
      <section className={styles.regressionSection}>
        <div className={styles.regressionEmpty}>
          <p className="eyebrow">INCOMPATIBLE BASELINE</p>
          <h3>The baseline run isn&apos;t comparable.</h3>
          <p>
            The baseline was recorded against a different scenario set and can&apos;t be compared
            to this run.
          </p>
        </div>
      </section>
    );
  }

  const comparison = response.comparison;

  return (
    <section className={styles.regressionSection} aria-label="Regression comparison">
      <RegressionSummary comparison={comparison} />
      <MetricDeltaTable changes={comparison.metric_changes} />
      <div className={styles.failureDiffGrid}>
        <FailureDiffColumn
          title="New Failures"
          tone="fail"
          entries={comparison.new_failures}
          emptyLabel="No new failures."
        />
        <FailureDiffColumn
          title="Resolved"
          tone="pass"
          entries={comparison.resolved_failures}
          emptyLabel="Nothing resolved."
        />
        <FailureDiffColumn
          title="Persistent"
          tone="warning"
          entries={comparison.persistent_failures}
          emptyLabel="No persistent failures."
        />
      </div>
    </section>
  );
}

function RegressionSummary({ comparison }: { comparison: RegressionComparison }) {
  const delta = comparison.score_delta;
  return (
    <div className={`${styles.regressionSummary} ${styles[comparison.status]}`}>
      <span className={styles.regressionStatusTag}>{REGRESSION_STATUS_LABELS[comparison.status]}</span>
      <div className={styles.regressionScoreRow}>
        <span>{comparison.baseline_score}</span>
        <i aria-hidden="true">→</i>
        <span>{comparison.current_score}</span>
        <strong>{delta > 0 ? `+${delta}` : delta}</strong>
      </div>
    </div>
  );
}

function MetricDeltaTable({ changes }: { changes: MetricComparison[] }) {
  return (
    <div className={styles.metricDeltaTable}>
      {changes.map((change) => (
        <div className={`${styles.metricDeltaRow} ${styles[change.status]}`} key={change.dimension}>
          <span className={styles.metricDeltaLabel}>{METRIC_LABELS[change.dimension]}</span>
          <span className={styles.metricDeltaValues}>
            {change.baseline_score === null ? "—" : change.baseline_score}
            <i aria-hidden="true">→</i>
            {change.current_score === null ? "—" : change.current_score}
          </span>
          <strong className={styles.metricDeltaChange}>
            {change.delta === null ? "N/A" : change.delta > 0 ? `+${change.delta}` : change.delta}
          </strong>
        </div>
      ))}
    </div>
  );
}

function FailureDiffColumn({
  title,
  tone,
  entries,
  emptyLabel,
}: {
  title: string;
  tone: "fail" | "pass" | "warning";
  entries: ScenarioFailure[];
  emptyLabel: string;
}) {
  return (
    <section className={`${styles.failureDiffColumn} ${styles[tone]}`}>
      <div className={styles.failureDiffHeading}>
        <h3>{title}</h3>
        <span>{entries.length}</span>
      </div>
      {entries.length === 0 ? (
        <p className={styles.emptyTab}>{emptyLabel}</p>
      ) : (
        <div className={styles.failureList}>
          {entries.map((entry, index) => (
            <FailureCard scenarioId={entry.scenario_id} failure={entry.failure} key={index} />
          ))}
        </div>
      )}
    </section>
  );
}

function ChecksView({ checks, error }: { checks: EvaluationCheck[]; error: ScenarioRunResult["error"] }) {
  if (error) {
    return (
      <div className={styles.scenarioError}>
        <strong>{error.category}</strong>
        <p>{error.reason}</p>
      </div>
    );
  }
  if (checks.length === 0) return <p className={styles.emptyTab}>No executable checks were recorded.</p>;

  return (
    <div className={styles.checkList}>
      {checks.map((check) => (
        <article className={`${styles.checkCard} ${styles[check.status]}`} key={check.check_id}>
          <div className={styles.checkHeading}>
            <span aria-hidden="true">{check.status === "pass" ? "✓" : "!"}</span>
            <div><code>{check.check_id}</code><strong>{check.reason}</strong></div>
            <small>{check.status}</small>
          </div>
          <dl className={styles.evidenceGrid}>
            <><dt>Check type</dt><dd>{check.type}</dd></>
            {check.category && <><dt>Category</dt><dd>{check.category}</dd></>}
            {check.severity && <><dt>Severity</dt><dd>{SEVERITY_LABELS[check.severity]}</dd></>}
            {check.evidence.expected_tool && <><dt>Expected tool</dt><dd>{check.evidence.expected_tool}</dd></>}
            {check.evidence.argument_name && <><dt>Argument</dt><dd>{check.evidence.argument_name}</dd></>}
            {check.evidence.argument_name && <><dt>Expected value</dt><dd>{displayValue(check.evidence.expected_value)}</dd></>}
            {check.evidence.actual_values.length > 0 && <><dt>Actual values</dt><dd>{displayValue(check.evidence.actual_values)}</dd></>}
            {check.evidence.condition && <><dt>Condition</dt><dd>{check.evidence.condition}</dd></>}
            {check.evidence.offending_event && <><dt>Offending event</dt><dd>{check.evidence.offending_event.id}</dd></>}
          </dl>
          <details className={styles.rawEvidence}>
            <summary>Raw evidence</summary>
            <pre>{JSON.stringify(check.evidence, null, 2)}</pre>
          </details>
        </article>
      ))}
    </div>
  );
}

function TranscriptView({ detail }: { detail: ScenarioRunResult }) {
  if (detail.transcript.length === 0) return <p className={styles.emptyTab}>No transcript was captured.</p>;
  return (
    <ol className={styles.transcriptList}>
      {detail.transcript.map((turn) => (
        <li className={styles[turn.role]} key={turn.sequence}>
          <span>{turn.role === "user" ? "USER" : "AGENT"} · {turn.sequence}</span>
          <p>{turn.content}</p>
        </li>
      ))}
    </ol>
  );
}

function ToolTraceView({ detail }: { detail: ScenarioRunResult }) {
  const offendingIds = new Set(
    detail.checks
      .filter((check) => check.status === "fail")
      .map((check) => check.evidence.offending_event?.id)
      .filter((id): id is string => Boolean(id)),
  );
  if (detail.tool_trace.length === 0) return <p className={styles.emptyTab}>No tool calls were observed.</p>;
  return (
    <ol className={styles.toolTrace}>
      {detail.tool_trace.map((event, index) => (
        <ToolTraceEvent
          event={event}
          sequence={index + 1}
          isOffending={offendingIds.has(event.id)}
          key={event.id}
        />
      ))}
    </ol>
  );
}

function ToolTraceEvent({ event, sequence, isOffending }: { event: ToolEvent; sequence: number; isOffending: boolean }) {
  return (
    <li className={isOffending ? styles.offendingEvent : ""}>
      <span className={styles.traceSequence}>{sequence}</span>
      <div>
        <div className={styles.traceHeading}>
          <code>{event.tool}</code>
          <time dateTime={event.timestamp}>{eventTime(event.timestamp)}</time>
        </div>
        {isOffending && <strong className={styles.offendingLabel}>POLICY VIOLATION EVIDENCE</strong>}
        <dl>
          {Object.entries(event.arguments).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
          ))}
        </dl>
        <small>event {event.id}</small>
      </div>
    </li>
  );
}

function CoverageView({ detail }: { detail: ScenarioRunResult }) {
  return (
    <div className={styles.coverage}>
      <div className={styles.scopeCard}>
        <span>EVALUATION SCOPE</span>
        <code>{detail.evaluation_scope}</code>
        <p>Only structured tool contracts determine pass or fail in this MVP.</p>
      </div>

      <CoverageList
        title="Declared check IDs"
        items={detail.declared_checks}
        note="Declarative fixture metadata; these names are not executable evaluator configuration."
      />
      <CoverageList
        title="Unscored declared checks"
        items={detail.unscored_declared_checks}
        note="Not evaluated in this MVP. Their presence does not imply coverage."
        warning
      />
      <CoverageList
        title="Unscored expectations"
        items={detail.unscored_expectations}
        note="Human-readable expectations retained for transparency, not semantic scoring."
        warning
      />
    </div>
  );
}

function CoverageList({
  title,
  items,
  note,
  warning = false,
}: {
  title: string;
  items: string[];
  note: string;
  warning?: boolean;
}) {
  return (
    <section className={`${styles.coverageList} ${warning ? styles.coverageWarning : ""}`}>
      <div><h3>{title}</h3><span>{items.length}</span></div>
      <p>{note}</p>
      {items.length > 0 ? <ul>{items.map((item) => <li key={item}><code>{item}</code></li>)}</ul> : <small>None declared.</small>}
    </section>
  );
}

function LoadingBlock({ label }: { label: string }) {
  return <div className={styles.loadingBlock} role="status"><span aria-hidden="true" />{label}</div>;
}
