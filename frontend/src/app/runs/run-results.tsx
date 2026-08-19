"use client";

import { useState } from "react";

import type {
  EvaluationCheck,
  Failure,
  MetricScore,
  ScenarioResultSummary,
  ScenarioRunResult,
  ToolEvent,
} from "@/lib/api";

import styles from "./runs.module.css";
import {
  CATEGORY_LABELS,
  FAILURE_FILTERS,
  METRIC_LABELS,
  METRIC_STATUS_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
  TAB_LABELS,
  displayValue,
  eventTime,
  type DetailTab,
  type FailureFilter,
} from "./runs-ui";
import { LoadingBlock } from "./run-history";

export function ResultList({
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
        <div>
          <p className="eyebrow">SCENARIOS</p>
          <h2>Results</h2>
        </div>
        <span>{results.length}</span>
      </div>
      <div className={styles.resultButtons}>
        {results.map((result) => (
          <button
            type="button"
            key={result.scenario_id}
            className={`${styles.resultButton} ${styles[result.status]} ${
              selectedScenarioId === result.scenario_id ? styles.resultSelected : ""
            }`}
            onClick={() => onSelect(result.scenario_id)}
            aria-pressed={selectedScenarioId === result.scenario_id}
          >
            <span className={styles.resultStatus} aria-hidden="true">
              {result.status === "pass" ? "✓" : result.status === "fail" ? "!" : "×"}
            </span>
            <span className={styles.resultText}>
              <span>
                <strong>{result.scenario_id}</strong>
                <small>{STATUS_LABELS[result.status]}</small>
              </span>
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

export function ResultDetail({
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
          <h2 id="scenario-detail-title">
            {summary.scenario_id} · {summary.title}
          </h2>
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
          <div className={styles.detailError} role="alert">
            {error}
          </div>
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
          <strong className={styles.metricScore}>
            {metric.score === null ? "—" : metric.score}
          </strong>
          <p>{metric.reason}</p>
        </article>
      ))}
    </div>
  );
}

function FailuresView({ failures }: { failures: Failure[] }) {
  const [filter, setFilter] = useState<FailureFilter>("all");
  const filtered =
    filter === "all" ? failures : failures.filter((failure) => failure.severity === filter);

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

export function FailureCard({
  failure,
  scenarioId,
}: {
  failure: Failure;
  scenarioId?: string;
}) {
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

function ChecksView({
  checks,
  error,
}: {
  checks: EvaluationCheck[];
  error: ScenarioRunResult["error"];
}) {
  if (error) {
    return (
      <div className={styles.scenarioError}>
        <strong>{error.category}</strong>
        <p>{error.reason}</p>
      </div>
    );
  }
  if (checks.length === 0)
    return <p className={styles.emptyTab}>No executable checks were recorded.</p>;

  return (
    <div className={styles.checkList}>
      {checks.map((check) => (
        <article className={`${styles.checkCard} ${styles[check.status]}`} key={check.check_id}>
          <div className={styles.checkHeading}>
            <span aria-hidden="true">{check.status === "pass" ? "✓" : "!"}</span>
            <div>
              <code>{check.check_id}</code>
              <strong>{check.reason}</strong>
            </div>
            <small>{check.status}</small>
          </div>
          <dl className={styles.evidenceGrid}>
            <>
              <dt>Check type</dt>
              <dd>{check.type}</dd>
            </>
            {check.category && (
              <>
                <dt>Category</dt>
                <dd>{check.category}</dd>
              </>
            )}
            {check.severity && (
              <>
                <dt>Severity</dt>
                <dd>{SEVERITY_LABELS[check.severity]}</dd>
              </>
            )}
            {check.evidence.expected_tool && (
              <>
                <dt>Expected tool</dt>
                <dd>{check.evidence.expected_tool}</dd>
              </>
            )}
            {check.evidence.prerequisite_tool && (
              <>
                <dt>Prerequisite</dt>
                <dd>{check.evidence.prerequisite_tool}</dd>
              </>
            )}
            {check.evidence.argument_name && (
              <>
                <dt>Argument</dt>
                <dd>{check.evidence.argument_name}</dd>
              </>
            )}
            {check.type === "tool_argument_constraint" && check.evidence.argument_name && (
              <>
                <dt>Expected value</dt>
                <dd>{displayValue(check.evidence.expected_value)}</dd>
              </>
            )}
            {check.evidence.allowed_values.length > 0 && (
              <>
                <dt>Allowed values</dt>
                <dd>{displayValue(check.evidence.allowed_values)}</dd>
              </>
            )}
            {check.evidence.pattern && (
              <>
                <dt>Pattern</dt>
                <dd>{check.evidence.pattern}</dd>
              </>
            )}
            {(check.evidence.min_value !== null || check.evidence.max_value !== null) && (
              <>
                <dt>Range</dt>
                <dd>
                  {check.evidence.min_value === null ? "−∞" : check.evidence.min_value} →{" "}
                  {check.evidence.max_value === null ? "+∞" : check.evidence.max_value}
                </dd>
              </>
            )}
            {check.evidence.actual_values.length > 0 && (
              <>
                <dt>Actual values</dt>
                <dd>{displayValue(check.evidence.actual_values)}</dd>
              </>
            )}
            {check.evidence.condition && (
              <>
                <dt>Condition</dt>
                <dd>{check.evidence.condition}</dd>
              </>
            )}
            {check.evidence.offending_event && (
              <>
                <dt>Offending event</dt>
                <dd>{check.evidence.offending_event.id}</dd>
              </>
            )}
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
  if (detail.transcript.length === 0)
    return <p className={styles.emptyTab}>No transcript was captured.</p>;
  return (
    <ol className={styles.transcriptList}>
      {detail.transcript.map((turn) => (
        <li className={styles[turn.role]} key={turn.sequence}>
          <span>
            {turn.role === "user" ? "USER" : "AGENT"} · {turn.sequence}
          </span>
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
  if (detail.tool_trace.length === 0)
    return <p className={styles.emptyTab}>No tool calls were observed.</p>;
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

function ToolTraceEvent({
  event,
  sequence,
  isOffending,
}: {
  event: ToolEvent;
  sequence: number;
  isOffending: boolean;
}) {
  return (
    <li className={isOffending ? styles.offendingEvent : ""}>
      <span className={styles.traceSequence}>{sequence}</span>
      <div>
        <div className={styles.traceHeading}>
          <code>{event.tool}</code>
          <time dateTime={event.timestamp}>{eventTime(event.timestamp)}</time>
        </div>
        {isOffending && (
          <strong className={styles.offendingLabel}>POLICY VIOLATION EVIDENCE</strong>
        )}
        <dl>
          {Object.entries(event.arguments).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{displayValue(value)}</dd>
            </div>
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
      <div>
        <h3>{title}</h3>
        <span>{items.length}</span>
      </div>
      <p>{note}</p>
      {items.length > 0 ? (
        <ul>
          {items.map((item) => (
            <li key={item}>
              <code>{item}</code>
            </li>
          ))}
        </ul>
      ) : (
        <small>None declared.</small>
      )}
    </section>
  );
}
