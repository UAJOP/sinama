"""Offline, zero-cost semantic judge used for calibration work only.

This adapter talks to a locally running Ollama daemon so SINAMA's hand-labeled
Turkish calibration set can be executed without any paid provider dependency or
API key.

Deliberate boundaries:

* It is NOT a production semantic provider. ``SemanticJudgeProvider`` has no
  ``ollama`` member and ``build_semantic_judge`` never constructs this class, so
  no value of ``SINAMA_SEMANTIC_JUDGE_PROVIDER`` can route a scenario run here.
* It is reachable only from the ``sinama-semantic-calibrate`` CLI. No FastAPI
  route builds it, so no caller-supplied localhost URL is exposed through the
  product API.
* The destination is pinned to loopback. That keeps this from becoming a general
  outbound HTTP client and leaves the external-agent SSRF boundary in
  ``http_agent.py`` untouched and authoritative for agent traffic.
"""

import ipaddress
import json
import time
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.semantic_judge import (
    SEMANTIC_OUTPUT_SCHEMA,
    ProviderOutput,
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticJudgeError,
    SemanticJudgeRequest,
    SemanticJudgeUsage,
    build_semantic_checks,
)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


class LocalJudgeConfigurationError(ValueError):
    """Raised when a calibration-only local endpoint is not a loopback address."""


def validate_loopback_base_url(base_url: str) -> str:
    """Reject anything that is not a local daemon.

    The local judge is a developer calibration tool. Restricting it to loopback
    means an operator cannot repurpose it into an arbitrary outbound HTTP client.
    """

    candidate = base_url.strip().rstrip("/")
    if not candidate:
        raise LocalJudgeConfigurationError("Local semantic judge URL must not be empty.")

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise LocalJudgeConfigurationError("Local semantic judge URL must be http or https.")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise LocalJudgeConfigurationError("Local semantic judge URL must not carry credentials.")

    host = (parsed.hostname or "").casefold()
    if host in _LOOPBACK_HOSTNAMES:
        return candidate
    try:
        if ipaddress.ip_address(host).is_loopback:
            return candidate
    except ValueError:
        pass
    raise LocalJudgeConfigurationError(
        "Local semantic judge URL must point at a loopback address such as "
        f"{DEFAULT_OLLAMA_BASE_URL}."
    )


class OllamaSemanticJudge:
    """Local Ollama chat adapter satisfying the shared ``SemanticJudge`` protocol."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        max_input_chars: int,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = validate_loopback_base_url(base_url)
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_input_chars = max_input_chars
        self._transport = transport

    @property
    def provider(self) -> str:
        return "ollama-local"

    @property
    def model(self) -> str:
        return self._model

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/api/chat"

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        serialized = request.model_dump_json()
        if len(serialized) > self._max_input_chars:
            raise SemanticJudgeError("Semantic evaluation input exceeded the configured limit.")

        payload = {
            "model": self._model,
            "stream": False,
            # qwen3 and similar models emit reasoning blocks by default; disabling
            # keeps the response body schema-clean and cuts local latency.
            "think": False,
            "format": SEMANTIC_OUTPUT_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an advisory reliability evaluator. Evaluate ONLY the supplied "
                        "semantic expectations against the masked conversation transcript. Do "
                        "not infer tool calls. Return one check per expectation. Use uncertain "
                        "when the evidence is insufficient. assistant_turns must contain "
                        "transcript sequence numbers for assistant messages that materially "
                        "support the verdict. Respond with JSON only."
                    ),
                },
                {"role": "user", "content": f"INPUT:\n{serialized}"},
            ],
        }

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException:
            raise SemanticJudgeError("Semantic judge request exceeded its deadline.") from None
        except httpx.RequestError:
            raise SemanticJudgeError(
                "Local semantic judge is unreachable. Is the Ollama daemon running?"
            ) from None

        if response.status_code < 200 or response.status_code >= 300:
            raise SemanticJudgeError("Semantic judge provider returned a non-success status.")

        try:
            payload_json = response.json()
            output_text = self._extract_output_text(payload_json)
            provider_output = ProviderOutput.model_validate_json(output_text)
            usage = self._usage_from_response(payload_json)
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError):
            raise SemanticJudgeError(
                "Semantic judge provider returned an invalid response."
            ) from None

        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
            checks=build_semantic_checks(request, provider_output),
            latency_ms=max(0, round((time.perf_counter() - started) * 1_000)),
            usage=usage,
        )

    @staticmethod
    def _extract_output_text(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        return content

    @staticmethod
    def _usage_from_response(payload: dict[str, object]) -> SemanticJudgeUsage | None:
        def token(name: str) -> int | None:
            value = payload.get(name)
            return value if isinstance(value, int) and value >= 0 else None

        input_tokens = token("prompt_eval_count")
        output_tokens = token("eval_count")
        if input_tokens is None and output_tokens is None:
            return None
        total = None
        if input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        return SemanticJudgeUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            # A local daemon has no billable cost; report it explicitly as zero.
            estimated_cost_usd=0.0,
        )
