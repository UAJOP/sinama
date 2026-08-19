import type { ScenarioRunResult } from "@/lib/api";

import styles from "./runs.module.css";

type SemanticStatus = "not_applicable" | "disabled" | "completed" | "error";
type SemanticVerdict = "pass" | "fail" | "uncertain";

type SemanticCheck = {
  expectation_id: string;
  type: "unsupported_promise" | "intent_satisfaction" | "internal_instruction_disclosure";
  verdict: SemanticVerdict;
  reason: string;
  assistant_turns: number[];
};

type SemanticReport = {
  status: SemanticStatus;
  mode: "shadow";
  advisory_only: true;
  provider: string | null;
  model: string | null;
  checks: SemanticCheck[];
  latency_ms: number | null;
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    estimated_cost_usd: number | null;
  } | null;
  error: string | null;
};

type SemanticScenarioResult = ScenarioRunResult & {
  semantic_evaluation?: SemanticReport | null;
};

const VERDICT_LABELS: Record<SemanticVerdict, string> = {
  pass: "Pass",
  fail: "Fail",
  uncertain: "Uncertain",
};

const TYPE_LABELS: Record<SemanticCheck["type"], string> = {
  unsupported_promise: "Unsupported promise",
  intent_satisfaction: "Intent satisfaction",
  internal_instruction_disclosure: "Internal instruction disclosure",
};

export function SemanticShadowView({ detail }: { detail: ScenarioRunResult }) {
  const report = (detail as SemanticScenarioResult).semantic_evaluation ?? null;

  if (report === null || report.status === "not_applicable") {
    return (
      <p className={styles.emptyTab}>
        This scenario does not declare any semantic shadow expectations.
      </p>
    );
  }

  if (report.status === "disabled") {
    return (
      <div className={styles.coverage}>
        <div className={styles.scopeCard}>
          <span>SEMANTIC SHADOW</span>
          <code>disabled</code>
          <p>
            This scenario declares semantic expectations, but the optional semantic judge is not
            enabled. Deterministic evaluation remains fully authoritative.
          </p>
        </div>
      </div>
    );
  }

  if (report.status === "error") {
    return (
      <div className={styles.coverage}>
        <div className={styles.scopeCard}>
          <span>SEMANTIC SHADOW</span>
          <code>provider error</code>
          <p>{report.error ?? "Semantic evaluation could not be completed."}</p>
          <p>This advisory error does not change the deterministic scenario result.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.coverage}>
      <div className={styles.scopeCard}>
        <span>SEMANTIC SHADOW · ADVISORY ONLY</span>
        <code>
          {report.provider ?? "judge"} · {report.model ?? "model"}
        </code>
        <p>
          Semantic verdicts are additional evidence only. They do not change deterministic
          pass/fail, regression comparison or release readiness.
        </p>
        <p>
          {report.latency_ms !== null ? `${report.latency_ms} ms` : "Latency unavailable"}
          {report.usage?.total_tokens !== null && report.usage?.total_tokens !== undefined
            ? ` · ${report.usage.total_tokens} tokens`
            : ""}
        </p>
      </div>

      <div className={styles.checkList}>
        {report.checks.map((check) => {
          const tone = check.verdict === "uncertain" ? "warning" : check.verdict;
          return (
            <article
              className={`${styles.checkCard} ${styles[tone]}`}
              key={check.expectation_id}
            >
              <div className={styles.checkHeading}>
                <span aria-hidden="true">
                  {check.verdict === "pass" ? "✓" : check.verdict === "fail" ? "!" : "?"}
                </span>
                <div>
                  <code>{check.expectation_id}</code>
                  <strong>{TYPE_LABELS[check.type]}</strong>
                </div>
                <small>{VERDICT_LABELS[check.verdict]}</small>
              </div>
              <p>{check.reason}</p>
              <dl className={styles.evidenceGrid}>
                <dt>Mode</dt>
                <dd>Shadow / non-blocking</dd>
                <dt>Assistant evidence</dt>
                <dd>
                  {check.assistant_turns.length > 0
                    ? check.assistant_turns.map((turn) => `#${turn}`).join(", ")
                    : "No specific assistant turn cited"}
                </dd>
              </dl>
            </article>
          );
        })}
      </div>
    </div>
  );
}
