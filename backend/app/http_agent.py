import asyncio
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import Field, SecretStr, StringConstraints, ValidationError, field_validator

from app.agent_adapters import (
    AgentRequestError,
    AgentSession,
    AgentTimeoutError,
    AgentTurnResult,
    MalformedAgentResponseError,
)
from app.config import get_settings
from app.models import JsonScalar, NonEmptyMessage, StrictModel, ToolEvent, ToolIdentifier

EndpointUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]
AddressResolver = Callable[[str, int], Awaitable[Sequence[str]]]

_BLOCKED_HOSTNAMES = {
    "instance-data",
    "localhost",
    "metadata",
    "metadata.azure.internal",
    "metadata.google.internal",
    "metadata.google.internal.",
}
_BLOCKED_HOST_SUFFIXES = (".internal", ".local", ".localhost", ".home.arpa")


class ExternalAgentConfiguration(StrictModel):
    endpoint_url: EndpointUrl
    bearer_token: SecretStr | None = None

    @field_validator("bearer_token")
    @classmethod
    def limit_bearer_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value()
        if len(token) > 4_096:
            raise ValueError("Bearer token exceeds the maximum supported length.")
        if any(ord(character) < 32 or ord(character) == 127 for character in token):
            raise ValueError("Bearer token contains unsupported control characters.")
        return value


class ExternalToolEvent(StrictModel):
    # External agents may expose domain-specific tools. Keep the identifier
    # constrained, but do not force it into the built-in insurance demo enum.
    tool: ToolIdentifier
    arguments: dict[str, JsonScalar] = Field(default_factory=dict, max_length=50)


class ExternalTurnRequest(StrictModel):
    conversation_id: str
    message: NonEmptyMessage


class ExternalTurnResponse(StrictModel):
    message: NonEmptyMessage
    tool_events: list[ExternalToolEvent] = Field(default_factory=list, max_length=100)


class ConnectionTestStatus(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    INVALID_RESPONSE_SCHEMA = "invalid_response_schema"
    RESPONSE_TOO_LARGE = "response_too_large"
    BLOCKED_URL = "blocked_url"
    NETWORK_ERROR = "network_error"


class ConnectionTestResult(StrictModel):
    status: ConnectionTestStatus
    message: str
    http_status_code: int | None = None
    observed_tool_events: int = Field(default=0, ge=0)


class UnsafeAgentEndpointError(AgentRequestError):
    """Raised when an endpoint violates the outbound request policy."""


class ExternalAgentHttpStatusError(AgentRequestError):
    def __init__(self, status_code: int) -> None:
        super().__init__("External agent returned a non-success HTTP status.")
        self.status_code = status_code


class ExternalAgentNetworkError(AgentRequestError):
    """Raised for sanitized transport failures."""


class ExternalAgentResponseTooLargeError(AgentRequestError):
    """Raised when the response exceeds the configured byte limit."""


class InvalidAgentJsonError(MalformedAgentResponseError):
    """Raised when a response body is not valid JSON."""


class InvalidAgentSchemaError(MalformedAgentResponseError):
    """Raised when JSON does not match the external turn contract."""


@dataclass(frozen=True)
class ValidatedAgentEndpoint:
    request_url: httpx.URL
    host_header: str | None = None
    sni_hostname: str | None = None


async def resolve_host_addresses(host: str, port: int) -> Sequence[str]:
    def resolve() -> Sequence[str]:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple({str(record[4][0]) for record in records})

    return await asyncio.to_thread(resolve)


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


async def validate_external_agent_endpoint(
    endpoint_url: str,
    *,
    production: bool,
    resolver: AddressResolver = resolve_host_addresses,
) -> ValidatedAgentEndpoint:
    if any(character.isspace() for character in endpoint_url):
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")

    try:
        parsed = urlsplit(endpoint_url)
        port = parsed.port
    except ValueError:
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.") from None

    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")
    if port == 0:
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")
    if production and scheme != "https":
        raise UnsafeAgentEndpointError("Production external agents must use HTTPS.")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")

    try:
        normalized_url = httpx.URL(endpoint_url)
    except (httpx.InvalidURL, UnicodeError):
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.") from None

    host = parsed.hostname
    if host is None:
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")
    normalized_host = host.casefold().rstrip(".")
    if (
        normalized_host in _BLOCKED_HOSTNAMES
        or normalized_host.endswith(_BLOCKED_HOST_SUFFIXES)
    ):
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")

    try:
        literal_address = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal_address = None

    if literal_address is not None:
        if not literal_address.is_global:
            raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")
        return ValidatedAgentEndpoint(request_url=normalized_url)

    try:
        addresses = await resolver(normalized_host, port or (443 if scheme == "https" else 80))
    except Exception:
        raise UnsafeAgentEndpointError(
            "External agent endpoint could not be resolved safely."
        ) from None
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise UnsafeAgentEndpointError("External agent endpoint is not allowed.")

    resolved_address = str(ipaddress.ip_address(addresses[0]))
    original_host = normalized_url.raw_host.decode("ascii")
    return ValidatedAgentEndpoint(
        request_url=normalized_url.copy_with(host=resolved_address),
        host_header=normalized_url.netloc.decode("ascii"),
        sni_hostname=original_host if scheme == "https" else None,
    )


@dataclass(repr=False)
class HttpAgentAdapter:
    endpoint_url: str
    bearer_token: SecretStr | None = None
    timeout_seconds: float = 4.0
    max_response_bytes: int = 262_144
    production: bool = False
    resolver: AddressResolver = resolve_host_addresses
    transport: httpx.AsyncBaseTransport | None = None
    configuration_label: str = "external_http"

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 5:
            raise ValueError("timeout_seconds must be greater than zero and at most five")
        if self.max_response_bytes < 1_024 or self.max_response_bytes > 1_048_576:
            raise ValueError("max_response_bytes must be between 1024 and 1048576")

    @property
    def label(self) -> str:
        return self.configuration_label

    async def start_session(self) -> AgentSession:
        return AgentSession(session_id=str(uuid4()))

    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        try:
            return await asyncio.wait_for(
                self._send_message(session, message),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            raise AgentTimeoutError("External agent request exceeded its deadline.") from None

    async def _send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        destination = await validate_external_agent_endpoint(
            self.endpoint_url,
            production=self.production,
            resolver=self.resolver,
        )
        request = ExternalTurnRequest(conversation_id=session.session_id, message=message)
        payload = await self._post(request.model_dump(mode="json"), destination)

        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InvalidAgentJsonError("External agent returned invalid JSON.") from None
        try:
            response = ExternalTurnResponse.model_validate(decoded)
        except ValidationError:
            raise InvalidAgentSchemaError(
                "External agent response did not match the required schema."
            ) from None

        timestamp = datetime.now(UTC)
        return AgentTurnResult(
            assistant_message=response.message,
            tool_events=[
                ToolEvent(
                    id=uuid4(),
                    tool=event.tool,
                    arguments=event.arguments,
                    timestamp=timestamp,
                )
                for event in response.tool_events
            ],
        )

    async def _post(
        self,
        payload: dict[str, object],
        destination: ValidatedAgentEndpoint,
    ) -> bytes:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if destination.host_header is not None:
            headers["Host"] = destination.host_header
        if self.bearer_token is not None and self.bearer_token.get_secret_value():
            headers["Authorization"] = f"Bearer {self.bearer_token.get_secret_value()}"

        extensions = (
            {"sni_hostname": destination.sni_hostname}
            if destination.sni_hostname is not None
            else None
        )

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(self.timeout_seconds),
                transport=self.transport,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    destination.request_url,
                    json=payload,
                    headers=headers,
                    extensions=extensions,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise ExternalAgentHttpStatusError(response.status_code)
                    return await self._read_limited_response(response)
        except AgentRequestError:
            raise
        except httpx.TimeoutException:
            raise AgentTimeoutError("External agent request exceeded its deadline.") from None
        except httpx.RequestError:
            raise ExternalAgentNetworkError("External agent request failed.") from None
        except Exception:
            raise ExternalAgentNetworkError("External agent request failed.") from None

    async def _read_limited_response(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > self.max_response_bytes:
                raise ExternalAgentResponseTooLargeError(
                    "External agent response exceeded the configured size limit."
                )

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self.max_response_bytes:
                raise ExternalAgentResponseTooLargeError(
                    "External agent response exceeded the configured size limit."
                )
        return bytes(body)


def build_http_agent_adapter(configuration: ExternalAgentConfiguration) -> HttpAgentAdapter:
    settings = get_settings()
    return HttpAgentAdapter(
        endpoint_url=configuration.endpoint_url,
        bearer_token=configuration.bearer_token,
        timeout_seconds=settings.external_agent_timeout_seconds,
        max_response_bytes=settings.external_agent_max_response_bytes,
        production=settings.is_production,
    )


async def test_http_agent_connection(adapter: HttpAgentAdapter) -> ConnectionTestResult:
    try:
        session = await adapter.start_session()
        turn = await adapter.send_message(session, "SINAMA connection test")
    except AgentTimeoutError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.TIMEOUT,
            message="External agent did not respond before the timeout.",
        )
    except ExternalAgentHttpStatusError as error:
        return ConnectionTestResult(
            status=ConnectionTestStatus.HTTP_ERROR,
            message="External agent returned a non-success HTTP status.",
            http_status_code=error.status_code,
        )
    except InvalidAgentJsonError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.INVALID_JSON,
            message="External agent returned invalid JSON.",
        )
    except InvalidAgentSchemaError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.INVALID_RESPONSE_SCHEMA,
            message="External agent response did not match the required schema.",
        )
    except ExternalAgentResponseTooLargeError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.RESPONSE_TOO_LARGE,
            message="External agent response exceeded the configured size limit.",
        )
    except UnsafeAgentEndpointError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.BLOCKED_URL,
            message="External agent endpoint is blocked by the outbound request policy.",
        )
    except AgentRequestError:
        return ConnectionTestResult(
            status=ConnectionTestStatus.NETWORK_ERROR,
            message="External agent could not be reached safely.",
        )

    return ConnectionTestResult(
        status=ConnectionTestStatus.SUCCESS,
        message="External agent connection succeeded.",
        observed_tool_events=len(turn.tool_events),
    )
