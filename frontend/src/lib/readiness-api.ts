import type {
  ComparisonAvailability,
  EvaluationCheckType,
  RegressionStatus,
  Severity,
} from "@/lib/api";

export type ReleaseReadinessVerdict = "ready" | "warning" | "blocked";
export type ReadinessReasonLevel = "warning" | "blocker";
export type ReadinessReasonCode =
  | "run_not_completed"
  | "run_execution_error"
  | "scenario_execution_error"
  | "critical_failure"
  | "high_failure"
  | "non_blocking_failure"
  | "regression_detected"
  | "no_baseline_comparison"
  | "incompatible_baseline";

export interface ReadinessReason {
  code: ReadinessReasonCode;
  level: ReadinessReasonLevel;
  title: string;
  detail: string;
  scenario_id: string | null;
  failure_type: EvaluationCheckType | null;
  failure_severity: Severity | null;
}

export interface ReleaseReadinessResponse {
  run_id: string;
  verdict: ReleaseReadinessVerdict;
  reasons: ReadinessReason[];
  comparison_status: ComparisonAvailability | null;
  regression_status: RegressionStatus | null;
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function getRunReadiness(
  runId: string,
  signal?: AbortSignal,
): Promise<ReleaseReadinessResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/runs/${runId}/readiness`, {
      method: "GET",
      cache: "no-store",
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new Error("Release readiness could not reach the SINAMA backend.");
  }

  if (!response.ok) {
    let detail = `Release readiness request failed (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep the safe status-based message when the server does not return JSON.
    }
    throw new Error(detail);
  }

  return (await response.json()) as ReleaseReadinessResponse;
}
