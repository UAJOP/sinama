"use client";

import { useEffect, useState } from "react";

import {
  listRunTrends,
  type RegressionStatus,
  type RunTrendPoint,
  type RunTrendResponse,
} from "@/lib/api";

import styles from "./run-trends.module.css";
import { isAbortError, runTimestamp } from "./runs-ui";

const DIRECTION_LABELS: Record<RegressionStatus, string> = {
  improved: "Improved",
  stable: "Stable",
  regression: "Regression",
};

function directionClass(direction: RegressionStatus | null): string {
  if (direction === "improved") return styles.improved;
  if (direction === "regression") return styles.regression;
  if (direction === "stable") return styles.stable;
  return "";
}

function TrendRow({ point }: { point: RunTrendPoint }) {
  const version = point.agent_version ?? "Unversioned";
  const delta = point.score_delta;

  return (
    <div className={styles.row}>
      <div className={styles.identity}>
        <strong>{version}</strong>
        <small>{point.agent_label}</small>
        {point.is_baseline && <em>BASELINE</em>}
      </div>

      <div className={styles.score}>
        {point.score === null ? (
          <strong className={styles.errorScore}>—</strong>
        ) : (
          <>
            <strong>{point.score}</strong>
            <span className={styles.track} aria-hidden="true">
              <span style={{ width: `${point.score}%` }} />
            </span>
          </>
        )}
      </div>

      <div className={`${styles.direction} ${directionClass(point.direction)}`}>
        {point.lifecycle_status === "error" ? (
          <span>Execution error</span>
        ) : point.direction ? (
          <>
            <span>{DIRECTION_LABELS[point.direction]}</span>
            <strong>{delta !== null && delta > 0 ? `+${delta}` : (delta ?? "—")}</strong>
          </>
        ) : (
          <span>First compatible run</span>
        )}
      </div>

      <div className={styles.outcomes}>
        <span className={styles.pass}>{point.outcomes.passed} pass</span>
        <span className={styles.fail}>{point.outcomes.failed} fail</span>
        <span className={styles.error}>{point.outcomes.errors} error</span>
      </div>

      <div className={styles.severity}>
        {point.severities.critical > 0 && (
          <span className={styles.critical}>{point.severities.critical} critical</span>
        )}
        {point.severities.high > 0 && (
          <span className={styles.high}>{point.severities.high} high</span>
        )}
        {point.severities.critical === 0 && point.severities.high === 0 && <span>0 high+</span>}
      </div>

      <time className={styles.time} dateTime={point.created_at}>
        {runTimestamp(point.created_at)}
      </time>
    </div>
  );
}

export function RunTrends({ packId, reloadKey }: { packId: string; reloadKey: number }) {
  const [response, setResponse] = useState<RunTrendResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!packId) return;

    const controller = new AbortController();

    void listRunTrends(packId, 20, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setResponse(payload);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) {
          setError(
            cause instanceof Error ? cause.message : "Reliability trends could not be loaded.",
          );
        }
      });

    return () => controller.abort();
  }, [packId, reloadKey, retryKey]);

  const loading = Boolean(packId) && !error && response?.pack_id !== packId;

  return (
    <section className={styles.section} aria-labelledby="reliability-trends-title">
      <div className={styles.header}>
        <div>
          <h2 id="reliability-trends-title">Reliability trend</h2>
          <p>
            Version-by-version movement using the same deterministic Goal Completion score and
            regression threshold as run comparison. New critical failures still force regression.
          </p>
        </div>
        <code>{packId || "no pack"}</code>
      </div>

      {loading ? (
        <div className={styles.state} role="status">
          Loading version history…
        </div>
      ) : error ? (
        <div className={styles.state} role="alert">
          {error}
          <button
            type="button"
            onClick={() => {
              setError(null);
              setResponse(null);
              setRetryKey((value) => value + 1);
            }}
          >
            Retry
          </button>
        </div>
      ) : !response || response.points.length === 0 ? (
        <div className={styles.state}>No completed or errored runs for this pack yet.</div>
      ) : (
        <div className={styles.table}>
          <div className={`${styles.row} ${styles.labels}`} aria-hidden="true">
            <span>Version / agent</span>
            <span>Score</span>
            <span>Direction</span>
            <span>Outcomes</span>
            <span>Severity</span>
            <span>Created</span>
          </div>
          {response.points.map((point) => (
            <TrendRow point={point} key={point.run_id} />
          ))}
        </div>
      )}
    </section>
  );
}
