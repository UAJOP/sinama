import type {
  AgentMode,
  AgentTarget,
  ConnectionTestStatus,
  JsonScalar,
  MetricDimension,
  MetricStatus,
  RegressionStatus,
  RunLifecycleStatus,
  ScenarioCategory,
  ScenarioResultSummary,
  ScenarioRunStatus,
  Severity,
  TestRunSummary,
} from "@/lib/api";

export type DetailTab =
  | "checks"
  | "metrics"
  | "failures"
  | "semantic"
  | "transcript"
  | "trace"
  | "coverage";
export type ConnectionState = "idle" | "testing" | ConnectionTestStatus;
export type FailureFilter = "all" | Severity;
export type RunView = "results" | "regression";

export const TARGET_OPTIONS: { value: AgentTarget; label: string; note: string }[] = [
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

export const MODE_OPTIONS: { value: AgentMode; label: string; note: string }[] = [
  { value: "healthy", label: "Healthy", note: "Expected safe behavior" },
  {
    value: "broken_premature_submission",
    label: "Broken: Premature Submission",
    note: "Known regression target",
  },
];

export const LIFECYCLE_LABELS: Record<RunLifecycleStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  error: "Execution error",
};

export const STATUS_LABELS: Record<ScenarioRunStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  error: "Error",
};

export const CATEGORY_LABELS: Record<ScenarioCategory, string> = {
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

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const TAB_LABELS: Record<DetailTab, string> = {
  checks: "Checks",
  metrics: "Metrics",
  failures: "Failures",
  semantic: "Semantic Shadow",
  transcript: "Transcript",
  trace: "Tool Trace",
  coverage: "Coverage",
};

export const METRIC_LABELS: Record<MetricDimension, string> = {
  goal_completion: "Goal Completion",
  tool_usage: "Tool Usage",
  handoff: "Handoff",
  safety: "Safety",
  conversation_quality: "Conversation Quality",
};

export const METRIC_STATUS_LABELS: Record<MetricStatus, string> = {
  pass: "Pass",
  warning: "Warning",
  fail: "Fail",
  not_applicable: "N/A",
};

export const FAILURE_FILTERS: FailureFilter[] = [
  "all",
  "critical",
  "high",
  "medium",
  "low",
];

export const REGRESSION_STATUS_LABELS: Record<RegressionStatus, string> = {
  improved: "Improved",
  stable: "Stable",
  regression: "Regression",
};

export const RUN_VIEW_LABELS: Record<RunView, string> = {
  results: "Scenario Results",
  regression: "Regression",
};

export const TERMINAL_STATUSES: RunLifecycleStatus[] = ["completed", "error"];
export const POLL_DELAY_MS = 350;
export const MAX_POLL_FAILURES = 4;
export const RECENT_RUNS_LIMIT = 20;
/** Mirrors AGENT_VERSION_MAX_LENGTH in the backend. */
export const AGENT_VERSION_MAX_LENGTH = 64;

/** Prefer the user's version label, falling back to SINAMA's derived label. */
export function runIdentity(run: TestRunSummary): string {
  return run.agent_version ?? run.agent_label;
}

export function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

export function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

export function displayValue(value: JsonScalar | JsonScalar[] | undefined): string {
  if (value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function eventTime(timestamp: string): string {
  return new Intl.DateTimeFormat("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

export function resultSelection(results: ScenarioResultSummary[]): string | null {
  return (
    results.find((item) => item.status === "fail")?.scenario_id ??
    results[0]?.scenario_id ??
    null
  );
}

export function runTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : parsed.toLocaleString(undefined, {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}
