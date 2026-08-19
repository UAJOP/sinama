import type {
  ScenarioRunResult,
  SemanticExpectationType,
  SemanticJudgeCheck,
  SemanticVerdict,
} from "@/lib/api";

import styles from "./runs.module.css";

const VERDICT_LABELS: Record<SemanticVerdict, string> = {
  pass: "Advisory pass",
  fail: "Advisory concern",
  uncertain: "Advisory uncertain",
};

const VERDICT_GLYPHS: Record<SemanticVerdict, string> = {
  pass: "✓",
  fail: "!",
  uncertain: "?",
};

const TYPE_LABELS: Record<SemanticExpectationType, string> = {
  unsupported_promise: "Unsupported promise",
  intent_satisfaction: "Intent satisfaction",
  internal_instruction_disclosure: "Internal instruction disclosure",
};

/**
 * Semantic cards deliberately use their own `semanticVerdict*` classes rather than the
 * deterministic `.checkCard.fail` treatment, so an advisory concern is never mistaken
 * for the scenario itself failing.
 */
const VERDICT_CLASSES: Record<SemanticVerdict, string> = {
  pass: styles.semanticVerdictPass,
  fail: styles.semanticVerdictFail,
  uncertain: styles.semanticVerdictUncertain,
};

export function semanticVerdictClass(verdict: SemanticVerdict): string {
  return VERDICT_CLASSES[verdict];
}

export function semanticUsageSummary(
  latencyMs: number | null,
  totalTokens: number | null | undefined,
): string {
  const latency = latencyMs !== null ? `${latencyMs} ms` : "Latency unavailable";
  return typeof totalTokens === "number" ? `${latency} · ${totalTokens} tokens` : latency;
}

function AdvisoryNotice({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.coverage}>
      <div className={`${styles.scopeCard} ${styles.semanticScope}`}>
        <span>SEMANTIC SHADOW · ADVISORY ONLY</span>
        {children}
      </div>
    </div>
  );
}

export function SemanticShadowView({ detail }: { detail: ScenarioRunResult }) {
  const report = detail.semantic_evaluation ?? null;

  if (report === null || report.status === "not_applicable") {
    return (
      <p className={styles.emptyTab}>
        This scenario does not declare any semantic shadow expectations.
      </p>
    );
  }

  if (report.status === "disabled") {
    return (
      <AdvisoryNotice>
        <code>disabled</code>
        <p>
          This scenario declares semantic expectations, but the optional semantic judge is not
          enabled. Deterministic evaluation remains fully authoritative.
        </p>
      </AdvisoryNotice>
    );
  }

  if (report.status === "error") {
    return (
      <AdvisoryNotice>
        <code>advisory evaluation unavailable</code>
        <p>{report.error ?? "Semantic evaluation could not be completed."}</p>
        <p>
          This advisory error does not change the deterministic scenario result, regression
          comparison or release readiness.
        </p>
      </AdvisoryNotice>
    );
  }

  return (
    <div className={styles.coverage}>
      <div className={`${styles.scopeCard} ${styles.semanticScope}`}>
        <span>SEMANTIC SHADOW · ADVISORY ONLY</span>
        <code>
          {report.provider ?? "judge"} · {report.model ?? "model"}
        </code>
        <p>
          Semantic verdicts are additional evidence only. The scenario outcome above is decided
          entirely by deterministic checks; nothing here changes pass/fail, regression comparison
          or release readiness.
        </p>
        <p>{semanticUsageSummary(report.latency_ms, report.usage?.total_tokens)}</p>
      </div>

      <div className={styles.checkList}>
        {report.checks.map((check: SemanticJudgeCheck) => (
          <article
            className={`${styles.checkCard} ${styles.semanticCard} ${semanticVerdictClass(check.verdict)}`}
            key={check.expectation_id}
          >
            <div className={styles.checkHeading}>
              <span aria-hidden="true">{VERDICT_GLYPHS[check.verdict]}</span>
              <div>
                <code>{check.expectation_id}</code>
                <strong>{TYPE_LABELS[check.type]}</strong>
              </div>
              <small>{VERDICT_LABELS[check.verdict]}</small>
            </div>
            <p>{check.reason}</p>
            <dl className={styles.evidenceGrid}>
              <dt>Mode</dt>
              <dd>Shadow · non-blocking</dd>
              <dt>Assistant evidence</dt>
              <dd>
                {check.assistant_turns.length > 0
                  ? check.assistant_turns.map((turn) => `#${turn}`).join(", ")
                  : "No specific assistant turn cited"}
              </dd>
            </dl>
          </article>
        ))}
      </div>
    </div>
  );
}
