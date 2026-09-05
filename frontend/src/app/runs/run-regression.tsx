"use client";

import type {
  ExplicitRunComparisonResponse,
  MetricComparison,
  RegressionComparison,
  RegressionComparisonResponse,
  RegressionStatus,
  ScenarioFailure,
  TestRunSummary,
} from "@/lib/api";

import styles from "./runs.module.css";
import { FailureCard } from "./run-results";
import { LoadingBlock } from "./run-history";
import {
  METRIC_LABELS,
  REGRESSION_STATUS_LABELS,
  runIdentity,
  runTimestamp,
} from "./runs-ui";

export function CompareAgainstControl({
  candidates,
  referenceRunId,
  onChange,
  disabled,
}: {
  candidates: TestRunSummary[];
  referenceRunId: string | null;
  onChange: (referenceRunId: string | null) => void;
  disabled: boolean;
}) {
  return (
    <section className={styles.compareControl} aria-label="Comparison reference">
      <label>
        <span>Compare against</span>
        <select
          value={referenceRunId ?? ""}
          onChange={(event) => onChange(event.target.value || null)}
          disabled={disabled || candidates.length === 0}
        >
          <option value="">Pack baseline (default)</option>
          {candidates.map((candidate) => (
            <option value={candidate.run_id} key={candidate.run_id}>
              {runIdentity(candidate)} · {runTimestamp(candidate.created_at)}
              {candidate.is_baseline ? " · baseline" : ""}
            </option>
          ))}
        </select>
      </label>
      {referenceRunId ? (
        <button type="button" onClick={() => onChange(null)}>
          Back to baseline
        </button>
      ) : (
        <p className={styles.compareHint}>
          {candidates.length === 0
            ? "No other completed runs of this pack yet."
            : "Pick another completed run to compare this one against."}
        </p>
      )}
    </section>
  );
}

export function ExplicitComparisonView({
  response,
  isLoading,
  error,
}: {
  response: ExplicitRunComparisonResponse | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (isLoading) {
    return (
      <section className={styles.regressionSection}>
        <LoadingBlock label="Comparing runs…" />
      </section>
    );
  }
  if (error) {
    return (
      <section className={styles.regressionSection}>
        <div className={styles.detailError} role="alert">
          {error}
        </div>
      </section>
    );
  }
  if (!response) return null;

  const comparison = response.comparison;

  return (
    <section className={styles.regressionSection} aria-label="Explicit run comparison">
      <p className={styles.compareAxis}>
        <span>{runIdentity(response.reference_run)}</span>
        <span aria-hidden="true">→</span>
        <span>{runIdentity(response.current_run)}</span>
      </p>
      <RegressionSummary comparison={comparison} />
      <MetricDeltaTable changes={comparison.metric_changes} />
      <FailureDiffGrid comparison={comparison} />
    </section>
  );
}

export function RegressionView({
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
        <div className={styles.detailError} role="alert">
          {error}
        </div>
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
            The baseline was recorded against a different scenario set and can&apos;t be compared to
            this run.
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
      <FailureDiffGrid comparison={comparison} />
    </section>
  );
}

function FailureDiffGrid({ comparison }: { comparison: RegressionComparison }) {
  return (
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
  );
}

/**
 * Regression status and Release Readiness answer different questions, and a run can
 * legitimately read "Stable" here while readiness blocks it. Spelling that out where
 * the label appears stops the two from looking like duplicate status indicators.
 */
const REGRESSION_STATUS_HINTS: Record<RegressionStatus, string> = {
  improved: "Scored higher than the baseline under the current regression threshold.",
  stable: "No threshold-level change against the baseline. Release readiness is judged separately.",
  regression: "Moved past the regression threshold, or introduced a new critical failure.",
};

function RegressionSummary({ comparison }: { comparison: RegressionComparison }) {
  const delta = comparison.score_delta;
  return (
    <div className={styles.regressionSummaryBlock}>
      <div className={`${styles.regressionSummary} ${styles[comparison.status]}`}>
        <span className={styles.regressionStatusTag}>
          {REGRESSION_STATUS_LABELS[comparison.status]}
        </span>
        <div className={styles.regressionScoreRow}>
          <span>{comparison.baseline_score}</span>
          <i aria-hidden="true">→</i>
          <span>{comparison.current_score}</span>
          <strong>{delta > 0 ? `+${delta}` : delta}</strong>
        </div>
      </div>
      <p className={styles.regressionHint}>
        <strong>Change vs baseline.</strong> {REGRESSION_STATUS_HINTS[comparison.status]}
      </p>
    </div>
  );
}

function MetricDeltaTable({ changes }: { changes: MetricComparison[] }) {
  return (
    <div className={styles.metricDeltaTable}>
      {changes.map((change) => (
        <div
          className={`${styles.metricDeltaRow} ${styles[change.status]}`}
          key={change.dimension}
        >
          <span className={styles.metricDeltaLabel}>{METRIC_LABELS[change.dimension]}</span>
          <span className={styles.metricDeltaValues}>
            {change.baseline_score === null ? "—" : change.baseline_score}
            <i aria-hidden="true">→</i>
            {change.current_score === null ? "—" : change.current_score}
          </span>
          <strong className={styles.metricDeltaChange}>
            {change.delta === null
              ? "N/A"
              : change.delta > 0
                ? `+${change.delta}`
                : change.delta}
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
