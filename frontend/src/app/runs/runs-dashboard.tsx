"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  compareRuns,
  createTestRun,
  getRunComparison,
  getScenarioRunResult,
  getTestRunResults,
  listRecentRuns,
  listScenarioPacks,
  setRunBaseline,
  testExternalAgentConnection,
  type AgentMode,
  type AgentTarget,
  type ExplicitRunComparisonResponse,
  type RegressionComparisonResponse,
  type ScenarioPack,
  type ScenarioResultSummary,
  type ScenarioRunResult,
  type TestRunSummary,
} from "@/lib/api";

import { RunConfiguration } from "./run-configuration";
import { EmptyRunState, LoadingBlock, RecentRuns, RunOverview } from "./run-history";
import {
  CompareAgainstControl,
  ExplicitComparisonView,
  RegressionView,
} from "./run-regression";
import { ResultDetail, ResultList } from "./run-results";
import styles from "./runs.module.css";
import {
  RECENT_RUNS_LIMIT,
  RUN_VIEW_LABELS,
  TERMINAL_STATUSES,
  errorMessage,
  isAbortError,
  resultSelection,
  type ConnectionState,
  type DetailTab,
  type RunView,
} from "./runs-ui";
import { useRunPolling } from "./use-run-polling";

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
  const [agentVersion, setAgentVersion] = useState("");
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
  const [comparisonResponse, setComparisonResponse] =
    useState<RegressionComparisonResponse | null>(null);
  const [isLoadingComparison, setIsLoadingComparison] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [comparisonReload, setComparisonReload] = useState(0);
  const [isSettingBaseline, setIsSettingBaseline] = useState(false);
  const [baselineError, setBaselineError] = useState<string | null>(null);

  const [recentRuns, setRecentRuns] = useState<TestRunSummary[]>([]);
  const [recentRunsError, setRecentRunsError] = useState<string | null>(null);
  const [recentRunsReload, setRecentRunsReload] = useState(0);

  const [referenceRunId, setReferenceRunId] = useState<string | null>(null);
  const [explicitComparison, setExplicitComparison] =
    useState<ExplicitRunComparisonResponse | null>(null);
  const [isLoadingExplicit, setIsLoadingExplicit] = useState(false);
  const [explicitError, setExplicitError] = useState<string | null>(null);

  const createSerial = useRef(0);
  const pollSerial = useRef(0);
  const resultsSerial = useRef(0);
  const detailSerial = useRef(0);
  const connectionSerial = useRef(0);
  const comparisonSerial = useRef(0);
  const explicitSerial = useRef(0);

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

  useEffect(() => {
    const controller = new AbortController();

    void listRecentRuns(RECENT_RUNS_LIMIT, controller.signal)
      .then((payload) => {
        setRecentRuns(payload);
        setRecentRunsError(null);
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) {
          setRecentRunsError(errorMessage(cause, "Recent runs could not be loaded."));
        }
      });

    return () => controller.abort();
  }, [recentRunsReload]);

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

  const resetExplicitComparison = useCallback(() => {
    ++explicitSerial.current;
    setReferenceRunId(null);
    setExplicitComparison(null);
    setExplicitError(null);
    setIsLoadingExplicit(false);
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
    resetExplicitComparison();

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
        undefined,
        agentVersion.trim() || undefined,
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
    agentVersion,
    bearerToken,
    endpointUrl,
    externalConnectionReady,
    isCreating,
    resetExplicitComparison,
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
      setRecentRunsReload((value) => value + 1);
    } catch (cause) {
      setBaselineError(errorMessage(cause, "This run could not be set as the baseline."));
    } finally {
      setIsSettingBaseline(false);
    }
  }, [isSettingBaseline, run]);

  const handleOpenRun = useCallback(
    (summary: TestRunSummary) => {
      if (runIsActive || summary.run_id === run?.run_id) return;
      ++createSerial.current;
      ++pollSerial.current;
      ++resultsSerial.current;
      ++detailSerial.current;
      ++comparisonSerial.current;
      setRunError(null);
      setDetailError(null);
      setBaselineError(null);
      setComparisonError(null);
      setComparisonResponse(null);
      setResults([]);
      setSelectedScenarioId(null);
      setDetail(null);
      setActiveTab("checks");
      setRunView("results");
      setIsLoadingResults(TERMINAL_STATUSES.includes(summary.lifecycle_status));
      setIsLoadingComparison(TERMINAL_STATUSES.includes(summary.lifecycle_status));
      resetExplicitComparison();
      setRun(summary);
    },
    [resetExplicitComparison, run?.run_id, runIsActive],
  );

  useRunPolling({
    run,
    pollRetry,
    pollSerial,
    setRun,
    setIsLoadingResults,
    setIsLoadingComparison,
    setComparisonError,
    setComparisonResponse,
    setRecentRunsReload,
    setRunError,
  });

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
  }, [comparisonReload, terminalRunId]);

  useEffect(() => {
    if (!terminalRunId || !referenceRunId) return;

    const serial = ++explicitSerial.current;
    const controller = new AbortController();

    void compareRuns(terminalRunId, referenceRunId, controller.signal)
      .then((payload) => {
        if (serial === explicitSerial.current) setExplicitComparison(payload);
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause) && serial === explicitSerial.current) {
          setExplicitComparison(null);
          setExplicitError(errorMessage(cause, "These runs could not be compared."));
        }
      })
      .finally(() => {
        if (serial === explicitSerial.current) setIsLoadingExplicit(false);
      });

    return () => controller.abort();
  }, [referenceRunId, terminalRunId]);

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

  const comparisonCandidates = useMemo(
    () =>
      run
        ? recentRuns.filter(
            (candidate) =>
              candidate.run_id !== run.run_id &&
              candidate.lifecycle_status === "completed" &&
              candidate.pack_id === run.pack_id,
          )
        : [],
    [recentRuns, run],
  );

  return (
    <main className={styles.shell}>
      <header className={styles.pageHeader}>
        <div>
          <p className="eyebrow">AUTOMATED EVALUATION</p>
          <h1>Test Runs</h1>
          <p>
            Run the insurance pack against a built-in or external agent and inspect the same
            deterministic evidence.
          </p>
        </div>
        <span className={styles.storageNote}>LAST {RECENT_RUNS_LIMIT} RUNS</span>
      </header>

      <RunConfiguration
        packs={packs}
        packsLoading={packsLoading}
        packsError={packsError}
        selectedPackId={selectedPackId}
        selectedPack={selectedPack}
        selectedMode={selectedMode}
        agentTarget={agentTarget}
        endpointUrl={endpointUrl}
        bearerToken={bearerToken}
        agentVersion={agentVersion}
        connectionState={connectionState}
        connectionMessage={connectionMessage}
        isCreating={isCreating}
        runIsActive={runIsActive}
        externalConnectionReady={externalConnectionReady}
        onRetryPacks={() => {
          setPacksLoading(true);
          setPacksError(null);
          setPacksReload((value) => value + 1);
        }}
        onPackChange={setSelectedPackId}
        onTargetChange={(target) => {
          setAgentTarget(target);
          if (target === "built_in_demo") setBearerToken("");
          resetConnectionFeedback();
        }}
        onModeChange={setSelectedMode}
        onEndpointChange={(value) => {
          setEndpointUrl(value);
          resetConnectionFeedback();
        }}
        onBearerTokenChange={(value) => {
          setBearerToken(value);
          resetConnectionFeedback();
        }}
        onAgentVersionChange={setAgentVersion}
        onTestConnection={() => void handleTestConnection()}
        onCreateRun={() => void handleCreateRun()}
      />

      <RecentRuns
        runs={recentRuns}
        activeRunId={run?.run_id ?? null}
        error={recentRunsError}
        disabled={runIsActive}
        onOpen={handleOpenRun}
        onRetry={() => {
          setRecentRunsError(null);
          setRecentRunsReload((value) => value + 1);
        }}
      />

      {runError && (
        <div className={styles.errorBanner} role="alert">
          <div>
            <strong>Run unavailable</strong>
            <span>{runError}</span>
          </div>
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
            <>
              <CompareAgainstControl
                candidates={comparisonCandidates}
                referenceRunId={referenceRunId}
                onChange={(nextReferenceId) => {
                  ++explicitSerial.current;
                  setExplicitComparison(null);
                  setExplicitError(null);
                  setIsLoadingExplicit(nextReferenceId !== null);
                  setReferenceRunId(nextReferenceId);
                }}
                disabled={runIsActive}
              />
              {referenceRunId ? (
                <ExplicitComparisonView
                  response={explicitComparison}
                  isLoading={isLoadingExplicit}
                  error={explicitError}
                />
              ) : (
                <RegressionView
                  response={comparisonResponse}
                  isLoading={isLoadingComparison}
                  error={comparisonError}
                />
              )}
            </>
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
                summary={
                  results.find((item) => item.scenario_id === selectedScenarioId) ?? null
                }
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
