export type AgentMode = "healthy" | "broken_premature_submission";
export type AgentTarget = "built_in_demo" | "external_http";
export type JsonScalar = string | number | boolean | null;
export type RunLifecycleStatus = "queued" | "running" | "completed" | "error";
export type ScenarioRunStatus = "pass" | "fail" | "error";
export type Severity = "low" | "medium" | "high" | "critical";

export type ScenarioCategory =
  | "tool_call_policy"
  | "coverage_safety"
  | "privacy"
  | "human_handoff"
  | "prompt_injection"
  | "context_retention"
  | "ambiguous_intent"
  | "turkish_noise"
  | "repeated_request"
  | "failed_tool_recovery";

export type ToolName =
  | "lookup_policy"
  | "collect_claim_details"
  | "request_document"
  | "submit_claim"
  | "handoff_to_human";

export type ConversationPhase =
  | "awaiting_intent"
  | "awaiting_policy"
  | "awaiting_claim_details"
  | "awaiting_damage_photo"
  | "submitted"
  | "handed_off";

export interface ToolEvent {
  id: string;
  tool: ToolName;
  arguments: Record<string, JsonScalar>;
  timestamp: string;
}

export interface ConversationState {
  policy_number: string | null;
  policy_lookup_occurred: boolean;
  damage_description: string | null;
  damage_photo_exists: boolean;
  claim_submitted: boolean;
  phase: ConversationPhase;
  mode: AgentMode;
}

export interface ConversationResponse {
  conversation_id: string;
  mode: AgentMode;
  assistant_message: string;
  state: ConversationState;
  new_events: ToolEvent[];
}

export interface ScenarioPackScenario {
  scenario_id: string;
  title: string;
  category: ScenarioCategory;
  severity_if_failed: Severity;
}

export interface ScenarioPack {
  id: string;
  name: string;
  description: string;
  scenario_count: number;
  scenarios: ScenarioPackScenario[];
}

export interface RunAggregate {
  total: number;
  passed: number;
  failed: number;
  errors: number;
}

export interface RunExecutionError {
  category: "run_orchestration_error";
  reason: string;
}

export interface TestRunSummary {
  run_id: string;
  pack_id: string;
  pack_name: string;
  agent_target: AgentTarget;
  agent_mode: AgentMode;
  agent_label: string;
  /** Optional user-supplied version metadata. Distinct from agent_label. */
  agent_version: string | null;
  lifecycle_status: RunLifecycleStatus;
  aggregate: RunAggregate;
  completed_scenarios: number;
  total_scenarios: number;
  is_baseline: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: RunExecutionError | null;
}

export interface ScenarioResultSummary {
  scenario_id: string;
  title: string;
  category: ScenarioCategory;
  status: ScenarioRunStatus;
  severity: Severity | null;
  turns_executed: number;
  failed_check_count: number;
  execution_error_category: string | null;
}

export interface TestRunResultsResponse {
  run: TestRunSummary;
  results: ScenarioResultSummary[];
}

export interface EvaluationEvidence {
  expected_tool: ToolName | null;
  argument_name: string | null;
  expected_value: JsonScalar;
  actual_values: JsonScalar[];
  matching_event: ToolEvent | null;
  offending_event: ToolEvent | null;
  condition: string | null;
  tool_call_count: number | null;
  max_allowed: number | null;
  assistant_message_index: number | null;
  matched_phrase: string | null;
}

export type EvaluationCheckType =
  | "required_tool_call"
  | "tool_argument_constraint"
  | "forbidden_tool_call"
  | "tool_call_count"
  | "forbidden_phrase"
  | "required_phrase"
  | "possible_loop";

export type EvaluationCheckCategory =
  | "required_tool_missing"
  | "tool_argument_mismatch"
  | "tool_call_policy_violation"
  | "excessive_tool_calls"
  | "forbidden_phrase_detected"
  | "required_phrase_missing"
  | "possible_loop_detected";

export interface EvaluationCheck {
  check_id: string;
  type: EvaluationCheckType;
  status: "pass" | "fail";
  category: EvaluationCheckCategory | null;
  severity: Severity | null;
  reason: string;
  evidence: EvaluationEvidence;
}

export type MetricDimension =
  | "goal_completion"
  | "tool_usage"
  | "handoff"
  | "safety"
  | "conversation_quality";

export type MetricStatus = "pass" | "warning" | "fail" | "not_applicable";

export interface MetricScore {
  dimension: MetricDimension;
  score: number | null;
  status: MetricStatus;
  reason: string;
}

export interface Failure {
  type: EvaluationCheckType;
  severity: Severity;
  turn: number | null;
  title: string;
  description: string;
  expected: string;
  actual: string;
  suggestion: string;
}

export type RegressionStatus = "improved" | "stable" | "regression";
export type MetricComparisonStatus = "improved" | "stable" | "regressed" | "not_applicable";
export type ComparisonAvailability = "no_baseline" | "is_baseline" | "incompatible" | "available";

export interface MetricComparison {
  dimension: MetricDimension;
  baseline_score: number | null;
  current_score: number | null;
  delta: number | null;
  status: MetricComparisonStatus;
}

export interface ScenarioFailure {
  scenario_id: string;
  failure: Failure;
}

export interface RegressionComparison {
  baseline_run_id: string;
  current_run_id: string;
  pack_id: string;
  baseline_score: number;
  current_score: number;
  score_delta: number;
  status: RegressionStatus;
  metric_changes: MetricComparison[];
  new_failures: ScenarioFailure[];
  resolved_failures: ScenarioFailure[];
  persistent_failures: ScenarioFailure[];
}

export interface ExplicitRunComparisonResponse {
  reference_run: TestRunSummary;
  current_run: TestRunSummary;
  comparison: RegressionComparison;
}

export interface RegressionComparisonResponse {
  status: ComparisonAvailability;
  comparison: RegressionComparison | null;
}

export interface TranscriptTurn {
  sequence: number;
  role: "user" | "assistant";
  content: string;
}

export interface ScenarioExecutionError {
  category:
    | "missing_scenario"
    | "agent_timeout"
    | "malformed_agent_response"
    | "max_turns_exceeded"
    | "adapter_error";
  reason: string;
}

export interface ScenarioRunResult {
  scenario_id: string;
  scenario_version: string;
  agent_label: string;
  status: ScenarioRunStatus;
  severity: Severity | null;
  evaluation_scope: "deterministic_tool_contract";
  checks: EvaluationCheck[];
  declared_checks: string[];
  unscored_declared_checks: string[];
  transcript: TranscriptTurn[];
  tool_trace: ToolEvent[];
  turns_executed: number;
  unscored_expectations: string[];
  metrics: MetricScore[];
  failures: Failure[];
  error: ScenarioExecutionError | null;
}

export interface ExternalAgentConfiguration {
  endpoint_url: string;
  bearer_token?: string;
}

export type ConnectionTestStatus =
  | "success"
  | "timeout"
  | "http_error"
  | "invalid_json"
  | "invalid_response_schema"
  | "response_too_large"
  | "blocked_url"
  | "network_error";

export interface ConnectionTestResult {
  status: ConnectionTestStatus;
  message: string;
  http_status_code: number | null;
  observed_tool_events: number;
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw cause;
    }
    throw new Error(
      "Backend'e ulaşılamadı. FastAPI servisinin 8000 portunda çalıştığını kontrol edin.",
    );
  }

  if (!response.ok) {
    let detail = `API isteği başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the safe status-based message when the server does not return JSON.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function createConversation(mode: AgentMode): Promise<ConversationResponse> {
  return request("/api/demo-agent/conversations", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function sendConversationMessage(
  conversationId: string,
  message: string,
): Promise<ConversationResponse> {
  return request(`/api/demo-agent/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function resetConversation(conversationId: string): Promise<ConversationResponse> {
  return request(`/api/demo-agent/conversations/${conversationId}/reset`, {
    method: "POST",
  });
}

export function listScenarioPacks(signal?: AbortSignal): Promise<ScenarioPack[]> {
  return request("/api/scenario-packs", { method: "GET", signal });
}

export function createTestRun(
  packId: string,
  agentMode: AgentMode,
  agentTarget: AgentTarget,
  externalAgent?: ExternalAgentConfiguration,
  signal?: AbortSignal,
  agentVersion?: string,
): Promise<TestRunSummary> {
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({
      pack_id: packId,
      agent_mode: agentMode,
      agent_target: agentTarget,
      external_agent: externalAgent,
      // Omitted entirely when unset, so the request stays byte-identical to
      // what pre-versioning clients send.
      ...(agentVersion ? { agent_version: agentVersion } : {}),
    }),
    signal,
  });
}

export function testExternalAgentConnection(
  configuration: ExternalAgentConfiguration,
  signal?: AbortSignal,
): Promise<ConnectionTestResult> {
  return request("/api/agents/external/test-connection", {
    method: "POST",
    body: JSON.stringify(configuration),
    signal,
  });
}

export function listRecentRuns(
  limit = 20,
  signal?: AbortSignal,
): Promise<TestRunSummary[]> {
  return request(`/api/runs?limit=${limit}`, { method: "GET", signal });
}

/** Explicit reference -> current comparison. Never touches baseline state. */
export function compareRuns(
  currentRunId: string,
  referenceRunId: string,
  signal?: AbortSignal,
): Promise<ExplicitRunComparisonResponse> {
  return request(`/api/runs/${currentRunId}/compare/${referenceRunId}`, {
    method: "GET",
    signal,
  });
}

export function getTestRun(runId: string, signal?: AbortSignal): Promise<TestRunSummary> {
  return request(`/api/runs/${runId}`, { method: "GET", signal });
}

export function getTestRunResults(
  runId: string,
  signal?: AbortSignal,
): Promise<TestRunResultsResponse> {
  return request(`/api/runs/${runId}/results`, { method: "GET", signal });
}

export function getScenarioRunResult(
  runId: string,
  scenarioId: string,
  signal?: AbortSignal,
): Promise<ScenarioRunResult> {
  return request(`/api/runs/${runId}/results/${encodeURIComponent(scenarioId)}`, {
    method: "GET",
    signal,
  });
}

export function setRunBaseline(runId: string, signal?: AbortSignal): Promise<TestRunSummary> {
  return request(`/api/runs/${runId}/baseline`, { method: "POST", signal });
}

export function getRunComparison(
  runId: string,
  signal?: AbortSignal,
): Promise<RegressionComparisonResponse> {
  return request(`/api/runs/${runId}/comparison`, { method: "GET", signal });
}
