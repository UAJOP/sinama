"use client";

import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { getTestRun, type RegressionComparisonResponse, type TestRunSummary } from "@/lib/api";

import {
  MAX_POLL_FAILURES,
  POLL_DELAY_MS,
  TERMINAL_STATUSES,
  isAbortError,
} from "./runs-ui";

type PollingArgs = {
  run: TestRunSummary | null;
  pollRetry: number;
  pollSerial: MutableRefObject<number>;
  setRun: Dispatch<SetStateAction<TestRunSummary | null>>;
  setIsLoadingResults: Dispatch<SetStateAction<boolean>>;
  setIsLoadingComparison: Dispatch<SetStateAction<boolean>>;
  setComparisonError: Dispatch<SetStateAction<string | null>>;
  setComparisonResponse: Dispatch<SetStateAction<RegressionComparisonResponse | null>>;
  setRecentRunsReload: Dispatch<SetStateAction<number>>;
  setRunError: Dispatch<SetStateAction<string | null>>;
};

export function useRunPolling(args: PollingArgs) {
  const {
    run,
    pollRetry,
    pollSerial: pollSerialRef,
    setRun,
    setIsLoadingResults,
    setIsLoadingComparison,
    setComparisonError,
    setComparisonResponse,
    setRecentRunsReload,
    setRunError,
  } = args;

  useEffect(() => {
    if (!run || TERMINAL_STATUSES.includes(run.lifecycle_status)) return;

    const serial = ++pollSerialRef.current;
    const controller = new AbortController();
    let timer: number | undefined;
    let consecutiveFailures = 0;

    const poll = async () => {
      try {
        const current = await getTestRun(run.run_id, controller.signal);
        if (serial !== pollSerialRef.current || controller.signal.aborted) return;
        consecutiveFailures = 0;
        if (TERMINAL_STATUSES.includes(current.lifecycle_status)) {
          setIsLoadingResults(true);
          setIsLoadingComparison(true);
          setComparisonError(null);
          setComparisonResponse(null);
          setRecentRunsReload((value) => value + 1);
        }
        setRun(current);
        if (!TERMINAL_STATUSES.includes(current.lifecycle_status)) {
          timer = window.setTimeout(() => void poll(), POLL_DELAY_MS);
        }
      } catch (cause) {
        if (isAbortError(cause) || serial !== pollSerialRef.current) return;
        consecutiveFailures += 1;
        if (consecutiveFailures <= MAX_POLL_FAILURES) {
          timer = window.setTimeout(() => void poll(), POLL_DELAY_MS * consecutiveFailures);
        } else {
          setRunError(
            "Run status polling stopped after repeated connection failures. Retry the run.",
          );
        }
      }
    };

    timer = window.setTimeout(() => void poll(), 120);
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [
    pollRetry,
    pollSerialRef,
    run,
    setComparisonError,
    setComparisonResponse,
    setIsLoadingComparison,
    setIsLoadingResults,
    setRecentRunsReload,
    setRun,
    setRunError,
  ]);
}
