"use client";

import { useEffect, useState } from "react";

import {
  getRunReadiness,
  type ReadinessReason,
  type ReleaseReadinessResponse,
  type ReleaseReadinessVerdict,
} from "@/lib/readiness-api";

import styles from "./run-readiness.module.css";
import { isAbortError } from "./runs-ui";

const VERDICT_COPY: Record<
  ReleaseReadinessVerdict,
  { label: string; title: string; summary: string }
> = {
  ready: {
    label: "READY",
    title: "Ready to release",
    summary: "No deterministic blockers or unresolved comparison warnings were found.",
  },
  warning: {
    label: "WARNING",
    title: "Review before release",
    summary: "The run has no blocking evidence, but release context is incomplete or warnings remain.",
  },
  blocked: {
    label: "BLOCKED",
    title: "Release blocked",
    summary: "SINAMA found deterministic evidence that should block this agent version from release.",
  },
};

function Reason({ reason }: { reason: ReadinessReason }) {
  return (
    <article className={`${styles.reason} ${reason.level === "blocker" ? styles.blocker : ""}`}>
      <span className={styles.reasonMark}>{reason.level}</span>
      <div>
        <strong>{reason.title}</strong>
        <p>{reason.detail}</p>
        <div className={styles.meta}>
          <code>{reason.code}</code>
          {reason.scenario_id && <code>{reason.scenario_id}</code>}
          {reason.failure_severity && <code>{reason.failure_severity}</code>}
          {reason.failure_type && <code>{reason.failure_type}</code>}
        </div>
      </div>
    </article>
  );
}

export function RunReadiness({ runId, reloadKey }: { runId: string | null; reloadKey: number }) {
  const [response, setResponse] = useState<ReleaseReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();

    void getRunReadiness(runId, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setResponse(payload);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) {
          setError(cause instanceof Error ? cause.message : "Release readiness could not be loaded.");
        }
      });

    return () => controller.abort();
  }, [reloadKey, retryKey, runId]);

  if (!runId) return null;

  const loading = !error && response?.run_id !== runId;
  if (loading) {
    return (
      <div className={styles.state} role="status">
        Computing release readiness…
      </div>
    );
  }

  if (error) {
    return (
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
    );
  }

  if (!response) return null;
  const copy = VERDICT_COPY[response.verdict];

  return (
    <section className={`${styles.card} ${styles[response.verdict]}`} aria-labelledby="readiness-title">
      <div className={styles.head}>
        <div>
          <p className={styles.eyebrow}>RELEASE READINESS</p>
          <h2 id="readiness-title">{copy.title}</h2>
        </div>
        <span className={styles.badge}>{copy.label}</span>
      </div>
      <p className={styles.summary}>{copy.summary}</p>

      {response.reasons.length > 0 && (
        <div className={styles.reasons}>
          {response.reasons.map((reason, index) => (
            <Reason reason={reason} key={`${reason.code}:${reason.scenario_id ?? "run"}:${index}`} />
          ))}
        </div>
      )}
    </section>
  );
}
