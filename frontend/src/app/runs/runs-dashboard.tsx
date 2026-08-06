"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createTestRun,
  getScenarioRunResult,
  getTestRun,
  getTestRunResults,
  listScenarioPacks,
  type AgentMode,
  type EvaluationCheck,
  type JsonScalar,
  type RunLifecycleStatus,
  type ScenarioCategory,
  type ScenarioPack,
  type ScenarioResultSummary,
  type ScenarioRunResult,
  type ScenarioRunStatus,
  type Severity,
  type TestRunSummary,
  type ToolEvent,
} from "@/lib/api";

import styles from "./runs.module.css";

type DetailTab = "checks" | "transcript" | "trace" | "coverage";

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
};

const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const TAB_LABELS: Record<DetailTab, string> = {
  checks: "Checks",
  transcript: "Transcript",
  trace: "Tool Trace",
  coverage: "Coverage",
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

  const createSerial = useRef(0);
  const pollSerial = useRef(0);
  const resultsSerial = useRef(0);
  const detailSerial = useRef(0);

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

  const handleCreateRun = useCallback(async () => {
    if (!selectedPackId || isCreating || runIsActive) return;
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

    try {
      const created = await createTestRun(selectedPackId, selectedMode);
      if (serial !== createSerial.current) return;
      setRun(created);
    } catch (cause) {
      if (serial !== createSerial.current) return;
      setRunError(errorMessage(cause, "Test run could not be created."));
    } finally {
      if (serial === createSerial.current) setIsCreating(false);
    }
  }, [isCreating, runIsActive, selectedMode, selectedPackId]);

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
          <p>Run the built-in insurance pack and inspect deterministic evidence scenario by scenario.</p>
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

            <button
              className={styles.runButton}
              type="button"
              onClick={() => void handleCreateRun()}
              disabled={!selectedPackId || packsLoading || isCreating || runIsActive}
            >
              {isCreating ? "Starting…" : runIsActive ? "Run in progress" : "Run Test Pack"}
              <span aria-hidden="true">↗</span>
            </button>
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
          <RunOverview run={run} progressPercent={progressPercent} />
          {run.lifecycle_status === "error" && run.error && (
            <div className={styles.executionError} role="alert">
              <strong>{run.error.category}</strong>
              <span>{run.error.reason}</span>
            </div>
          )}

          {isLoadingResults ? (
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
          Choose Healthy for the expected baseline or Broken to surface the intentional
          premature-submission regression.
        </p>
        <ul className={styles.emptyFacts}>
          <li>5 synthetic Turkish scenarios</li>
          <li>Structured tool-contract evaluation</li>
          <li>No external API key required</li>
        </ul>
      </div>
    </section>
  );
}

function RunOverview({ run, progressPercent }: { run: TestRunSummary; progressPercent: number }) {
  const aggregateCards = [
    { label: "Total", value: run.aggregate.total, tone: "neutral", icon: "Σ" },
    { label: "Passed", value: run.aggregate.passed, tone: "pass", icon: "✓" },
    { label: "Failed", value: run.aggregate.failed, tone: "fail", icon: "!" },
    { label: "Errors", value: run.aggregate.errors, tone: "error", icon: "×" },
  ] as const;

  return (
    <section className={styles.overview} aria-labelledby="run-overview-title">
      <div className={styles.runIdentity}>
        <div>
          <p className="eyebrow">RUN</p>
          <h2 id="run-overview-title">{run.pack_name}</h2>
          <code>{run.run_id}</code>
        </div>
        <span className={`${styles.lifecycle} ${styles[run.lifecycle_status]}`}>
          <i aria-hidden="true" /> {LIFECYCLE_LABELS[run.lifecycle_status]}
        </span>
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
        <span>MODE <strong>{run.agent_mode === "healthy" ? "Healthy" : "Broken"}</strong></span>
        <span>PACK <strong>{run.pack_id}</strong></span>
        <span>OUTCOMES <strong>Observed results only</strong></span>
      </div>
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
  if (activeTab === "transcript") return <TranscriptView detail={detail} />;
  if (activeTab === "trace") return <ToolTraceView detail={detail} />;
  return <CoverageView detail={detail} />;
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
