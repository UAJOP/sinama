import asyncio
import json
import time
from enum import StrEnum
from typing import Literal, Protocol

import httpx
from pydantic import Field, SecretStr, ValidationError

from app.models import StrictModel

SEMANTIC_JUDGE_MAX_EXPECTATIONS = 8
SEMANTIC_JUDGE_MAX_ASSISTANT_TURNS = 20


class SemanticExpectationType(StrEnum):
    UNSUPPORTED_PROMISE = "unsupported_promise"
    INTENT_SATISFACTION = "intent_satisfaction"
    INTERNAL_INSTRUCTION_DISCLOSURE = "internal_instruction_disclosure"


class SemanticExpectation(StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    type: SemanticExpectationType
    rubric: str = Field(min_length=1, max_length=2_000)


class SemanticVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class SemanticEvaluationStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    DISABLED = "disabled"
    COMPLETED = "completed"
    ERROR = "error"


class SemanticTranscriptTurn(StrictModel):
    sequence: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4_000)


class SemanticJudgeRequest(StrictModel):
    scenario_id: str
    scenario_title: str
    initial_user_goal: str = Field(max_length=2_000)
    expectations: list[SemanticExpectation] = Field(
        min_length=1,
        max_length=SEMANTIC_JUDGE_MAX_EXPECTATIONS,
    )
    transcript: list[SemanticTranscriptTurn] = Field(
        max_length=SEMANTIC_JUDGE_MAX_ASSISTANT_TURNS * 2
    )


class SemanticJudgeCheck(StrictModel):
    expectation_id: str
    type: SemanticExpectationType
    verdict: SemanticVerdict
    reason: str = Field(min_length=1, max_length=1_000)
    assistant_turns: list[int] = Field(default_factory=list, max_length=10)


class SemanticJudgeUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class SemanticEvaluationReport(StrictModel):
    status: SemanticEvaluationStatus
    mode: Literal["shadow"] = "shadow"
    advisory_only: Literal[True] = True
    provider: str | None = None
    model: str | None = None
    checks: list[SemanticJudgeCheck] = Field(default_factory=list)
    latency_ms: int | None = Field(default=None, ge=0)
    usage: SemanticJudgeUsage | None = None
    error: str | None = None

    @classmethod
    def not_applicable(cls) -> "SemanticEvaluationReport":
        return cls(status=SemanticEvaluationStatus.NOT_APPLICABLE)

    @classmethod
    def disabled(cls) -> "SemanticEvaluationReport":
        return cls(status=SemanticEvaluationStatus.DISABLED)

    @classmethod
    def failed(cls, reason: str) -> "SemanticEvaluationReport":
        return cls(status=SemanticEvaluationStatus.ERROR, error=reason)


class SemanticJudgeError(RuntimeError):
    """Sanitized provider or semantic-contract failure."""


class SemanticJudge(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport: ...


class _ProviderCheck(StrictModel):
    expectation_id: str
    verdict: SemanticVerdict
    reason: str
    assistant_turns: list[int] = Field(default_factory=list)


class _ProviderOutput(StrictModel):
    checks: list[_ProviderCheck]


_OPENAI_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "expectation_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "fail", "uncertain"],
                    },
                    "reason": {"type": "string"},
                    "assistant_turns": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
                "required": [
                    "expectation_id",
                    "verdict",
                    "reason",
                    "assistant_turns",
                ],
            },
        }
    },
    "required": ["checks"],
}


class OpenAISemanticJudge:
    """Fixed-destination OpenAI Responses adapter for optional shadow evaluation."""

    _endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float,
        max_input_chars: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_input_chars = max_input_chars
        self._transport = transport

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        serialized = request.model_dump_json()
        if len(serialized) > self._max_input_chars:
            raise SemanticJudgeError("Semantic evaluation input exceeded the configured limit.")

        prompt = (
            "You are an advisory reliability evaluator. Evaluate ONLY the supplied semantic "
            "expectations against the masked conversation transcript. Do not infer tool calls. "
            "Return one check per expectation. Use uncertain when the evidence is insufficient. "
            "assistant_turns must contain transcript sequence numbers for assistant messages "
            "that materially support the verdict.\n\nINPUT:\n"
            f"{serialized}"
        )
        payload = {
            "model": self._model,
            "store": False,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sinama_semantic_shadow",
                    "strict": True,
                    "schema": _OPENAI_OUTPUT_SCHEMA,
                }
            },
            "max_output_tokens": 1_200,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self._endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException:
            raise SemanticJudgeError("Semantic judge request exceeded its deadline.") from None
        except httpx.RequestError:
            raise SemanticJudgeError("Semantic judge provider request failed.") from None

        if response.status_code < 200 or response.status_code >= 300:
            raise SemanticJudgeError("Semantic judge provider returned a non-success status.")

        try:
            payload_json = response.json()
            output_text = self._extract_output_text(payload_json)
            provider_output = _ProviderOutput.model_validate_json(output_text)
            usage = self._usage_from_response(payload_json)
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError):
            raise SemanticJudgeError(
                "Semantic judge provider returned an invalid response."
            ) from None

        expected_by_id = {item.id: item for item in request.expectations}
        returned_ids = [item.expectation_id for item in provider_output.checks]
        if (
            len(returned_ids) != len(set(returned_ids))
            or set(returned_ids) != set(expected_by_id)
        ):
            raise SemanticJudgeError(
                "Semantic judge response did not cover the expected rubric set."
            )

        assistant_sequences = {
            turn.sequence for turn in request.transcript if turn.role == "assistant"
        }
        checks: list[SemanticJudgeCheck] = []
        for item in provider_output.checks:
            if any(sequence not in assistant_sequences for sequence in item.assistant_turns):
                raise SemanticJudgeError(
                    "Semantic judge response referenced an invalid assistant turn."
                )
            expectation = expected_by_id[item.expectation_id]
            try:
                checks.append(
                    SemanticJudgeCheck(
                        expectation_id=item.expectation_id,
                        type=expectation.type,
                        verdict=item.verdict,
                        reason=item.reason,
                        assistant_turns=item.assistant_turns,
                    )
                )
            except ValidationError:
                # Field-level violations the provider schema cannot express (such as an
                # empty reason) are provider contract failures, not internal errors.
                raise SemanticJudgeError(
                    "Semantic judge provider returned an invalid response."
                ) from None

        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
            checks=checks,
            latency_ms=max(0, round((time.perf_counter() - started) * 1_000)),
            usage=usage,
        )

    @staticmethod
    def _extract_output_text(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError
        output = payload.get("output")
        if not isinstance(output, list):
            raise ValueError
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    return text
        raise ValueError

    @staticmethod
    def _usage_from_response(payload: dict[str, object]) -> SemanticJudgeUsage | None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None

        def token(name: str) -> int | None:
            value = usage.get(name)
            return value if isinstance(value, int) and value >= 0 else None

        return SemanticJudgeUsage(
            input_tokens=token("input_tokens"),
            output_tokens=token("output_tokens"),
            total_tokens=token("total_tokens"),
        )


async def run_semantic_shadow(
    judge: SemanticJudge,
    request: SemanticJudgeRequest,
    *,
    timeout_seconds: float,
) -> SemanticEvaluationReport:
    """Contain semantic failures so advisory evaluation cannot fail the agent run."""

    try:
        return await asyncio.wait_for(judge.evaluate(request), timeout=timeout_seconds)
    except TimeoutError:
        return SemanticEvaluationReport.failed(
            "Semantic evaluation exceeded the configured deadline."
        )
    except SemanticJudgeError as error:
        return SemanticEvaluationReport.failed(str(error))
    except Exception:
        return SemanticEvaluationReport.failed("Semantic evaluation failed unexpectedly.")
