import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from app.models import (
    AgentMode,
    ConversationPhase,
    ConversationResponse,
    ConversationState,
    ToolEvent,
    ToolName,
)

DEMO_POLICY_ID = "POL-DEMO-1001"
DEMO_CLAIM_ID = "CLM-DEMO-0001"
REQUIRED_DOCUMENT = "damage_photo"
WELCOME_MESSAGE = (
    "Merhaba, ben SINAMA'nın yerleşik Demo Sigorta Asistanıyım. "
    "Araç hasarı bildiriminizle ilgili nasıl yardımcı olabilirim?"
)


@dataclass
class Conversation:
    id: UUID
    state: ConversationState
    event_history: list[ToolEvent] = field(default_factory=list)


class ConversationNotFoundError(LookupError):
    pass


class DemoAgentService:
    """Deterministic, in-memory insurance agent used as a stable test target."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}
        self._lock = RLock()

    def create_conversation(self, mode: AgentMode) -> ConversationResponse:
        with self._lock:
            conversation = Conversation(
                id=uuid4(),
                state=ConversationState(mode=mode),
            )
            self._conversations[conversation.id] = conversation
            return self._response(conversation, WELCOME_MESSAGE, [])

    def reset_conversation(self, conversation_id: UUID) -> ConversationResponse:
        with self._lock:
            conversation = self._get_conversation(conversation_id)
            conversation.state = ConversationState(mode=conversation.state.mode)
            conversation.event_history.clear()
            return self._response(conversation, WELCOME_MESSAGE, [])

    def send_message(self, conversation_id: UUID, message: str) -> ConversationResponse:
        with self._lock:
            conversation = self._get_conversation(conversation_id)
            assistant_message, events = self._advance(conversation, message)
            conversation.event_history.extend(events)
            return self._response(conversation, assistant_message, events)

    def _get_conversation(self, conversation_id: UUID) -> Conversation:
        try:
            return self._conversations[conversation_id]
        except KeyError as error:
            raise ConversationNotFoundError(str(conversation_id)) from error

    def _advance(self, conversation: Conversation, message: str) -> tuple[str, list[ToolEvent]]:
        state = conversation.state
        normalized = message.casefold()

        if self._requests_human(normalized):
            event = self._event(
                ToolName.HANDOFF_TO_HUMAN,
                {"reason": "customer_request", "queue": "demo_claims_support"},
            )
            state.phase = ConversationPhase.HANDED_OFF
            return (
                "Talebinizi Demo Hasar Destek ekibine aktardım. "
                "Bu yalnızca sentetik bir devir olayıdır.",
                [event],
            )

        if state.phase in {ConversationPhase.SUBMITTED, ConversationPhase.HANDED_OFF}:
            return (
                "Bu demo görüşmesi tamamlandı. Yeni bir akış denemek için konuşmayı sıfırlayın.",
                [],
            )

        if state.phase is ConversationPhase.AWAITING_INTENT:
            policy_id = self._find_policy_id(message)
            if policy_id:
                return self._handle_policy(conversation, policy_id)
            state.phase = ConversationPhase.AWAITING_POLICY
            return (
                "Geçmiş olsun. Hasar kaydını başlatabilmem için poliçe numaranızı "
                "paylaşır mısınız?",
                [],
            )

        if state.phase is ConversationPhase.AWAITING_POLICY:
            policy_id = self._find_policy_id(message)
            if not policy_id:
                return (
                    "Poliçe numarasını `POL-DEMO-1001` biçiminde paylaşmanızı rica ederim.",
                    [],
                )
            return self._handle_policy(conversation, policy_id)

        if state.phase in {
            ConversationPhase.AWAITING_CLAIM_DETAILS,
            ConversationPhase.AWAITING_DAMAGE_PHOTO,
        }:
            return self._handle_claim_details(conversation, message)

        return ("Mesajınızı bu demo akışında işleyemedim. Lütfen konuşmayı sıfırlayın.", [])

    def _handle_policy(
        self, conversation: Conversation, policy_id: str
    ) -> tuple[str, list[ToolEvent]]:
        state = conversation.state
        is_valid = policy_id == DEMO_POLICY_ID
        lookup_event = self._event(
            ToolName.LOOKUP_POLICY,
            {"policy_id": policy_id, "found": is_valid},
        )
        state.policy_lookup_occurred = True

        if not is_valid:
            state.policy_number = None
            state.phase = ConversationPhase.AWAITING_POLICY
            return (
                "Bu sentetik poliçeyi bulamadım. Demo için `POL-DEMO-1001` numarasını kullanın.",
                [lookup_event],
            )

        state.policy_number = policy_id
        state.phase = ConversationPhase.AWAITING_CLAIM_DETAILS
        return (
            "Poliçeyi doğruladım: 2024 Demo Sedan. Hasarı kısaca anlatın ve hasar fotoğrafının "
            "hazır olup olmadığını belirtin.",
            [lookup_event],
        )

    def _handle_claim_details(
        self, conversation: Conversation, message: str
    ) -> tuple[str, list[ToolEvent]]:
        state = conversation.state
        photo_exists = self._message_has_photo(message)
        description = self._extract_damage_description(message)

        if description and (
            state.damage_description is None
            or len(description) > len(state.damage_description)
        ):
            state.damage_description = description
        state.damage_photo_exists = state.damage_photo_exists or photo_exists

        collect_event = self._event(
            ToolName.COLLECT_CLAIM_DETAILS,
            {
                "damage_description": state.damage_description or "not_provided",
                "damage_photo": state.damage_photo_exists,
            },
        )

        if state.damage_photo_exists:
            submit_event = self._event(
                ToolName.SUBMIT_CLAIM,
                {
                    "claim_id": DEMO_CLAIM_ID,
                    "status": "accepted",
                    "policy_id": state.policy_number,
                },
            )
            state.claim_submitted = True
            state.phase = ConversationPhase.SUBMITTED
            return (
                f"Gerekli fotoğrafı aldım ve sentetik hasar kaydını oluşturdum: {DEMO_CLAIM_ID}.",
                [collect_event, submit_event],
            )

        if state.mode is AgentMode.BROKEN_PREMATURE_SUBMISSION:
            submit_event = self._event(
                ToolName.SUBMIT_CLAIM,
                {
                    "claim_id": DEMO_CLAIM_ID,
                    "status": "premature",
                    "missing_requirement": REQUIRED_DOCUMENT,
                    "policy_id": state.policy_number,
                },
            )
            state.claim_submitted = True
            state.phase = ConversationPhase.SUBMITTED
            return (
                f"Fotoğraf olmadan ilerledim ve hasar kaydını oluşturdum: {DEMO_CLAIM_ID}.",
                [collect_event, submit_event],
            )

        request_event = self._event(
            ToolName.REQUEST_DOCUMENT,
            {"document_type": REQUIRED_DOCUMENT, "required_before": "submit_claim"},
        )
        state.phase = ConversationPhase.AWAITING_DAMAGE_PHOTO
        return (
            "Hasar dosyasını göndermeden önce araç hasar fotoğrafı zorunlu. Fotoğraf hazır "
            "olduğunda yükleyin; bu aşamada dosyayı göndermiyorum.",
            [collect_event, request_event],
        )

    @staticmethod
    def _find_policy_id(message: str) -> str | None:
        match = re.search(r"\bPOL-[A-Z0-9-]+\b", message.upper())
        return match.group(0) if match else None

    @staticmethod
    def _requests_human(normalized_message: str) -> bool:
        return any(term in normalized_message for term in ("insan", "temsilci", "canlı destek"))

    @staticmethod
    def _message_has_photo(message: str) -> bool:
        normalized = message.casefold()
        negative_terms = (
            "yok",
            "değil",
            "olmadan",
            "bulunmuyor",
            "henüz",
            "yüklemedim",
            "eklemedim",
            "göndermedim",
            "paylaşmadım",
        )
        positive_terms = ("yükledim", "ekledim", "gönderiyorum", "paylaşıyorum")
        mentions_photo = "fotoğraf" in normalized or "damage_photo" in normalized
        return (
            mentions_photo
            and any(term in normalized for term in positive_terms)
            and not any(term in normalized for term in negative_terms)
        )

    @staticmethod
    def _extract_damage_description(message: str) -> str | None:
        candidate = re.split(r"(?i)fotoğraf", message, maxsplit=1)[0].strip(" .")
        normalized = candidate.casefold()
        damage_terms = (
            "hasar",
            "hasarlı",
            "kırık",
            "kırıldı",
            "çatlak",
            "çizik",
            "ezik",
            "çöktü",
            "tampon",
            "kapı",
            "cam",
            "far",
            "çamurluk",
        )
        words = re.findall(r"\w+", normalized)
        if len(words) < 2 or not any(term in normalized for term in damage_terms):
            return None
        return candidate

    @staticmethod
    def _event(tool: ToolName, arguments: dict[str, str | int | float | bool | None]) -> ToolEvent:
        return ToolEvent(
            id=uuid4(),
            tool=tool,
            arguments=arguments,
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def _response(
        conversation: Conversation,
        assistant_message: str,
        events: list[ToolEvent],
    ) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conversation.id,
            mode=conversation.state.mode,
            assistant_message=assistant_message,
            state=conversation.state.model_copy(deep=True),
            new_events=events,
        )


demo_agent_service = DemoAgentService()
