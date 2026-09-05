"use client";

import Image from "next/image";

import type { RegressionComparisonResponse, TestRunSummary } from "@/lib/api";

import { RunReadiness } from "./run-readiness";
import styles from "./runs.module.css";
import {
  LIFECYCLE_LABELS,
  REGRESSION_STATUS_LABELS,
  TARGET_LABELS,
  runTimestamp,
} from "./runs-ui";

export function RecentRuns({
  runs,
  activeRunId,
  error,
  disabled,
  onOpen,
  onRetry,
}: {
  runs: TestRunSummary[];
  activeRunId: string | null;
  error: string | null;
  disabled: boolean;
  onOpen: (run: TestRunSummary) => void;
  onRetry: () => void;
}) {
  if (error) {
    return (
      <section className={styles.recentRuns} aria-labelledby="recent-runs-title">
        <div className={styles.recentRunsHead}>
          <h2 id="recent-runs-title">Recent runs</h2>
        </div>
        <div className={styles.inlineError} role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      </section>
    );
  }

  if (runs.length === 0) return null;

  return (
    <section className={styles.recentRuns} aria-labelledby="recent-runs-title">
      <div className={styles.recentRunsHead}>
        <h2 id="recent-runs-title">Recent runs</h2>
        <p>Reopen a stored run to inspect its evidence and regression comparison.</p>
      </div>
      <ul className={styles.recentRunsList}>
        {runs.map((item) => {
          const isActive = item.run_id === activeRunId;
          return (
            <li key={item.run_id}>
              <button
                type="button"
                className={isActive ? styles.recentRunActive : undefined}
                aria-current={isActive ? "true" : undefined}
                disabled={disabled && !isActive}
                onClick={() => onOpen(item)}
              >
                {/* Collection leads: two runs of different collections must not
                    look identical when scanning history. */}
                <span className={styles.recentRunTop}>
                  <strong>{item.pack_name}</strong>
                  {item.is_baseline && <em className={styles.baselineTag}>BASELINE</em>}
                </span>
                <span className={styles.recentRunMeta}>
                  <span>{TARGET_LABELS[item.agent_target]}</span>
                  <span aria-hidden="true">·</span>
                  <span>{LIFECYCLE_LABELS[item.lifecycle_status]}</span>
                  <span aria-hidden="true">·</span>
                  <span>{runTimestamp(item.created_at)}</span>
                </span>
                {item.agent_version && (
                  <span className={styles.versionTag}>{item.agent_version}</span>
                )}
                <span className={styles.recentRunCounts}>
                  {item.lifecycle_status === "completed" ? (
                    <>
                      <span className={styles.recentRunPass}>{item.aggregate.passed} pass</span>
                      <span className={styles.recentRunFail}>{item.aggregate.failed} fail</span>
                      <span className={styles.recentRunError}>{item.aggregate.errors} error</span>
                    </>
                  ) : (
                    <span>
                      {item.completed_scenarios}/{item.total_scenarios} scenarios
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function EmptyRunState() {
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
          <li>Multi-turn Turkish reliability scenarios</li>
          <li>Structured tool-contract evaluation</li>
          <li>No external API key required</li>
        </ul>
      </div>
    </section>
  );
}

export function RunOverview({
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

  const regressionBadge = run.is_baseline
    ? { label: "Baseline", status: "baseline" as const }
    : comparisonResponse?.status === "available" && comparisonResponse.comparison
      ? {
          label: REGRESSION_STATUS_LABELS[comparisonResponse.comparison.status],
          status: comparisonResponse.comparison.status,
        }
      : null;
  const readinessRunId =
    run.lifecycle_status === "completed" || run.lifecycle_status === "error" ? run.run_id : null;

  return (
    <>
      <section className={styles.overview} aria-labelledby="run-overview-title">
        <div className={styles.runIdentity}>
          <div>
            <p className="eyebrow">RUN</p>
            {/* What was tested, in one glance: collection, then the agent identity. */}
            <h2 id="run-overview-title">{run.pack_name}</h2>
            <p className={styles.runSubject}>
              <span>{run.pack_id}</span>
              <span aria-hidden="true">·</span>
              <span>{TARGET_LABELS[run.agent_target]}</span>
              {run.agent_version && (
                <>
                  <span aria-hidden="true">·</span>
                  <span className={styles.runSubjectVersion}>{run.agent_version}</span>
                </>
              )}
            </p>
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
          <span>
            {run.completed_scenarios} / {run.total_scenarios} scenarios observed
          </span>
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
              <span>
                <i aria-hidden="true">{card.icon}</i>
                {card.label}
              </span>
              <strong>{card.value}</strong>
            </div>
          ))}
        </div>
        <div className={styles.runMeta}>
          {run.agent_target === "built_in_demo" && (
            <span>
              MODE <strong>{run.agent_mode === "healthy" ? "Healthy" : "Broken"}</strong>
            </span>
          )}
          <span>
            STARTED <strong>{runTimestamp(run.created_at)}</strong>
          </span>
          <span>
            BASELINE <strong>{run.is_baseline ? "This run" : "Not this run"}</strong>
          </span>
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
          <p className={styles.baselineError} role="alert">
            {baselineError}
          </p>
        )}
      </section>
      <RunReadiness runId={readinessRunId} reloadKey={run.is_baseline ? 1 : 0} />
    </>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className={styles.loadingBlock} role="status">
      <span aria-hidden="true" />
      {label}
    </div>
  );
}
