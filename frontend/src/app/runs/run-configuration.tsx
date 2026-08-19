"use client";

import type { AgentMode, AgentTarget, ScenarioPack } from "@/lib/api";

import styles from "./runs.module.css";
import {
  AGENT_VERSION_MAX_LENGTH,
  MODE_OPTIONS,
  TARGET_OPTIONS,
  type ConnectionState,
} from "./runs-ui";

type RunConfigurationProps = {
  packs: ScenarioPack[];
  packsLoading: boolean;
  packsError: string | null;
  selectedPackId: string;
  selectedPack: ScenarioPack | null;
  selectedMode: AgentMode;
  agentTarget: AgentTarget;
  endpointUrl: string;
  bearerToken: string;
  agentVersion: string;
  connectionState: ConnectionState;
  connectionMessage: string | null;
  isCreating: boolean;
  runIsActive: boolean;
  externalConnectionReady: boolean;
  onRetryPacks: () => void;
  onPackChange: (packId: string) => void;
  onTargetChange: (target: AgentTarget) => void;
  onModeChange: (mode: AgentMode) => void;
  onEndpointChange: (value: string) => void;
  onBearerTokenChange: (value: string) => void;
  onAgentVersionChange: (value: string) => void;
  onTestConnection: () => void;
  onCreateRun: () => void;
};

export function RunConfiguration({
  packs,
  packsLoading,
  packsError,
  selectedPackId,
  selectedPack,
  selectedMode,
  agentTarget,
  endpointUrl,
  bearerToken,
  agentVersion,
  connectionState,
  connectionMessage,
  isCreating,
  runIsActive,
  externalConnectionReady,
  onRetryPacks,
  onPackChange,
  onTargetChange,
  onModeChange,
  onEndpointChange,
  onBearerTokenChange,
  onAgentVersionChange,
  onTestConnection,
  onCreateRun,
}: RunConfigurationProps) {
  return (
    <section className={styles.runControls} aria-labelledby="run-controls-title">
      <div className={styles.controlIntro}>
        <span className={styles.stepNumber}>01</span>
        <div>
          <h2 id="run-controls-title">Configure run</h2>
          <p>The selected mode applies only to the next run.</p>
        </div>
      </div>

      {packsError ? (
        <div className={styles.inlineError} role="alert">
          <span>{packsError}</span>
          <button type="button" onClick={onRetryPacks}>
            Retry
          </button>
        </div>
      ) : (
        <div className={styles.controlFields}>
          <label>
            <span>Scenario pack</span>
            <select
              value={selectedPackId}
              onChange={(event) => onPackChange(event.target.value)}
              disabled={packsLoading || isCreating || runIsActive}
            >
              {packsLoading && <option>Loading packs…</option>}
              {packs.map((pack) => (
                <option value={pack.id} key={pack.id}>
                  {pack.name} · {pack.scenario_count} scenarios
                </option>
              ))}
            </select>
          </label>

          <fieldset className={styles.modeField} disabled={isCreating || runIsActive}>
            <legend>Agent target</legend>
            <div className={styles.modeOptions}>
              {TARGET_OPTIONS.map((option) => (
                <label
                  className={agentTarget === option.value ? styles.modeSelected : ""}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="agent-target"
                    value={option.value}
                    checked={agentTarget === option.value}
                    onChange={() => onTargetChange(option.value)}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.note}</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <label>
            <span>Agent version (optional)</span>
            <input
              type="text"
              value={agentVersion}
              onChange={(event) => onAgentVersionChange(event.target.value)}
              placeholder="v1.4 · prod-2026-08-17"
              maxLength={AGENT_VERSION_MAX_LENGTH}
              disabled={isCreating || runIsActive}
            />
          </label>

          <button
            className={styles.runButton}
            type="button"
            onClick={onCreateRun}
            disabled={
              !selectedPackId ||
              packsLoading ||
              isCreating ||
              runIsActive ||
              !externalConnectionReady
            }
          >
            {isCreating ? "Starting…" : runIsActive ? "Run in progress" : "Run Test Pack"}
            <span aria-hidden="true">↗</span>
          </button>

          <div className={styles.agentConfiguration}>
            {agentTarget === "built_in_demo" ? (
              <fieldset className={styles.modeField} disabled={isCreating || runIsActive}>
                <legend>Agent mode</legend>
                <div className={styles.modeOptions}>
                  {MODE_OPTIONS.map((option) => (
                    <label
                      className={selectedMode === option.value ? styles.modeSelected : ""}
                      key={option.value}
                    >
                      <input
                        type="radio"
                        name="run-mode"
                        value={option.value}
                        checked={selectedMode === option.value}
                        onChange={() => onModeChange(option.value)}
                      />
                      <span>
                        <strong>{option.label}</strong>
                        <small>{option.note}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : (
              <div className={styles.externalConfiguration}>
                <label>
                  <span>Endpoint URL</span>
                  <input
                    type="url"
                    inputMode="url"
                    placeholder="https://agent.example.com/turn"
                    value={endpointUrl}
                    onChange={(event) => onEndpointChange(event.target.value)}
                    disabled={isCreating || runIsActive}
                    required
                  />
                </label>
                <label>
                  <span>Optional bearer token</span>
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder="Not stored"
                    value={bearerToken}
                    onChange={(event) => onBearerTokenChange(event.target.value)}
                    disabled={isCreating || runIsActive}
                  />
                </label>
                <button
                  className={styles.connectionButton}
                  type="button"
                  onClick={onTestConnection}
                  disabled={
                    !endpointUrl.trim() ||
                    connectionState === "testing" ||
                    isCreating ||
                    runIsActive
                  }
                >
                  {connectionState === "testing" ? "Testing…" : "Test connection"}
                </button>
                {connectionMessage && (
                  <p
                    className={`${styles.connectionFeedback} ${
                      connectionState === "success"
                        ? styles.connectionSuccess
                        : connectionState === "idle" || connectionState === "testing"
                          ? ""
                          : styles.connectionFailure
                    }`}
                    role={
                      connectionState === "idle" ||
                      connectionState === "success" ||
                      connectionState === "testing"
                        ? "status"
                        : "alert"
                    }
                  >
                    {connectionMessage}
                  </p>
                )}
                <small>
                  Bearer tokens stay only in this page&apos;s memory and are cleared after run
                  creation.
                </small>
              </div>
            )}
          </div>
        </div>
      )}

      {selectedPack && !packsError && (
        <p className={styles.packDescription}>
          <strong>{selectedPack.id}</strong> · {selectedPack.description}
        </p>
      )}
    </section>
  );
}
