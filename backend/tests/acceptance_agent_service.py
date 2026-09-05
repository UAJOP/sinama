"""A deterministic external agent service for the real-HTTP acceptance test.

This is test infrastructure, not a SINAMA feature. It is a vendor-neutral
customer-service agent that speaks SINAMA's existing external turn contract
(``ExternalTurnRequest`` in, ``ExternalTurnResponse`` out) and nothing else.

It is deliberately built on ``http.server`` rather than the product's FastAPI
stack so the acceptance test talks to a genuinely independent process-local HTTP
server over a real TCP socket, instead of re-entering SINAMA's own ASGI app.

Two behaviour versions exist so the same collection can be executed against a
healthy agent and a regressed one:

``healthy-v1``
    Verifies an order before acting on it.
``regressed-v2``
    Emits ``refund_order`` *before* its ``lookup_order`` prerequisite. That is the
    single intentional defect; every other behaviour is identical.

The defect is expressed purely as agent behaviour. SINAMA's evaluator has no
knowledge of these version names and needs none: the violation is caught by the
generic ``tool_order_constraints`` contract already declared by ECOM-001/ECOM-004.
"""

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_REQUEST_BYTES = 64 * 1024
ORDER_ID_PATTERN = re.compile(r"ORD-[A-Z0-9-]+")
DAMAGE_TERMS = ("kırık", "kırıldı", "hasarlı", "ezik")
HIGH_VALUE_THRESHOLD = 20_000


class BehaviourVersion(StrEnum):
    HEALTHY = "healthy-v1"
    REGRESSED = "regressed-v2"


@dataclass(frozen=True)
class CatalogOrder:
    return_eligible: bool
    value: int


# Deterministic order catalog covering the ecommerce-v1 pack fixtures.
ORDER_CATALOG: dict[str, CatalogOrder] = {
    "ORD-DEMO-1001": CatalogOrder(return_eligible=True, value=850),
    "ORD-DEMO-2002": CatalogOrder(return_eligible=True, value=45_000),
    "ORD-DEMO-3003": CatalogOrder(return_eligible=True, value=1_200),
}


class Outcome(StrEnum):
    OPEN = "open"
    NOT_FOUND = "not_found"
    REFUNDED = "refunded"
    ESCALATED = "escalated"


@dataclass
class ConversationState:
    order_id: str | None = None
    damage_reported: bool = False
    outcome: Outcome = Outcome.OPEN


@dataclass
class AgentBrain:
    """The whole agent. Pure, deterministic, and independent of SINAMA."""

    version: BehaviourVersion
    conversations: dict[str, ConversationState] = field(default_factory=dict)
    received_messages: list[tuple[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def respond(self, conversation_id: str, message: str) -> dict[str, object]:
        with self._lock:
            self.received_messages.append((conversation_id, message))
            state = self.conversations.setdefault(conversation_id, ConversationState())
            return self._respond_locked(state, message)

    def _respond_locked(self, state: ConversationState, message: str) -> dict[str, object]:
        lowered = message.casefold()
        if any(term in lowered for term in DAMAGE_TERMS):
            state.damage_reported = True

        found_id = ORDER_ID_PATTERN.search(message)
        if found_id is not None:
            state.order_id = found_id.group(0)

        if state.order_id is None:
            return _turn("Yardımcı olabilmem için sipariş numaranızı paylaşır mısınız?", [])

        if state.outcome is not Outcome.OPEN:
            return _turn(self._closing_message(state), [])

        order = ORDER_CATALOG.get(state.order_id)
        lookup = _tool_event(
            "lookup_order",
            {
                "order_id": state.order_id,
                "found": order is not None,
                **({"return_eligible": order.return_eligible} if order is not None else {}),
            },
        )

        if order is None:
            state.outcome = Outcome.NOT_FOUND
            return _turn(
                f"{state.order_id} numaralı siparişi sistemde bulamadım. "
                "Numarayı kontrol edip tekrar paylaşır mısınız?",
                [lookup],
            )

        if state.damage_reported and order.value >= HIGH_VALUE_THRESHOLD:
            state.outcome = Outcome.ESCALATED
            escalate = _tool_event(
                "escalate_return_case",
                {"order_id": state.order_id, "reason": "damaged_high_value"},
            )
            return _turn(
                "Siparişi doğruladım. Hasarlı ve yüksek tutarlı bir ürün olduğu için "
                "talebinizi uzman ekibimize aktardım.",
                [lookup, escalate],
            )

        state.outcome = Outcome.REFUNDED
        refund = _tool_event(
            "refund_order",
            {"order_id": state.order_id, "resolution": "refund"},
        )
        # The single intentional defect: the refund is emitted before the lookup
        # that is supposed to justify it. Everything else stays identical.
        events = (
            [refund, lookup] if self.version is BehaviourVersion.REGRESSED else [lookup, refund]
        )
        return _turn("Siparişi doğruladım ve iadenizi oluşturdum.", events)

    @staticmethod
    def _closing_message(state: ConversationState) -> str:
        if state.outcome is Outcome.NOT_FOUND:
            return "Bu numarayla eşleşen bir sipariş bulamadım, kontrol eder misiniz?"
        if state.outcome is Outcome.ESCALATED:
            return "Talebiniz uzman ekipte; en kısa sürede size dönüş yapılacak."
        return "Bu sipariş için iade zaten kaydedildi, ikinci kez oluşturmuyorum."


def _tool_event(tool: str, arguments: dict[str, object]) -> dict[str, object]:
    return {"tool": tool, "arguments": arguments}


def _turn(message: str, tool_events: list[dict[str, object]]) -> dict[str, object]:
    return {"message": message, "tool_events": tool_events}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    brain: AgentBrain

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        if self.path != "/turn":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid length"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send_json(400, {"error": "invalid length"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"error": "invalid payload"})
            return
        conversation_id = payload.get("conversation_id")
        message = payload.get("message")
        if not isinstance(conversation_id, str) or not isinstance(message, str):
            self._send_json(400, {"error": "invalid payload"})
            return

        self._send_json(200, self.brain.respond(conversation_id, message))

    def _send_json(self, status: int, body: dict[str, object]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default stderr access log during tests."""


@dataclass(frozen=True)
class RunningAgent:
    port: int
    brain: AgentBrain


@contextmanager
def running_demo_agent(version: BehaviourVersion) -> Iterator[RunningAgent]:
    """Bind a real TCP socket on loopback and serve the demo agent for the block."""

    brain = AgentBrain(version=version)
    handler = type("BoundHandler", (_Handler,), {"brain": brain})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield RunningAgent(port=server.server_address[1], brain=brain)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
