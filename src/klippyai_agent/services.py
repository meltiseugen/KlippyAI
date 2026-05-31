from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from uuid import uuid4

from klippyai_agent.intent import ChatIntentOutput, classify_deterministic_intent, route_for_intent
from klippyai_agent.schemas import (
    ArtifactInput,
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    ChatHistoryMessage,
    ConfigProposal,
    IssueFinding,
    PatchProposal,
    PrinterProfileSummary,
    SourceCitation,
    UiSessionResponse,
)
from klippyai_agent.sessions import InMemorySessionStore
from klippyai_agent.workflows import WorkflowContext

logger = logging.getLogger("klippyai_agent.chat")

_CONFIG_SECTION_PATTERN = re.compile(r"(?m)^\[[^\]\n]{1,160}\]\s*$")
_LOG_LINE_PATTERN = re.compile(
    r"(?m)^(?:"
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"|[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}"
    r"|Start printer at "
    r"|Traceback \(most recent call last\):"
    r"|MCU .+"
    r"|!! .+"
    r")"
)
_MAX_HISTORY_CHARS_PER_MESSAGE = 1400


@dataclass(slots=True)
class ChatService:
    provider_name: str
    root_path: str
    diagnosis_graph: object
    config_graph: object
    workflow_context: WorkflowContext
    sessions: InMemorySessionStore
    provider_model: str | None = None
    conversation_history_pairs: int = 10

    async def create_ui_session(self) -> UiSessionResponse:
        session = self.sessions.create()
        logger.info("Created UI session session_id=%s expires_at=%s", session.session_id, session.expires_at.isoformat())
        return UiSessionResponse(
            session_id=session.session_id,
            embed_path=f"{self.root_path}/embed?session={session.session_id}" if self.root_path else f"/embed?session={session.session_id}",
            expires_at=session.expires_at,
        )

    async def bootstrap(self, session_id: str) -> BootstrapResponse:
        session = self.sessions.get(session_id)
        if not session:
            logger.warning("Rejected bootstrap for invalid or expired session session_id=%s", session_id)
            raise ValueError("Invalid or expired session.")

        moonraker_reachable = await self.workflow_context.collector.ping()
        klipper_reachable = await self.workflow_context.collector.ping_printer() if moonraker_reachable else False
        logger.info(
            "Bootstrap session_id=%s provider=%s provider_model=%s moonraker_reachable=%s klipper_reachable=%s profile=%s",
            session_id,
            self.provider_name,
            self.provider_model or "unavailable",
            moonraker_reachable,
            klipper_reachable,
            self.workflow_context.profile.summary_label() or "unavailable",
        )
        return BootstrapResponse(
            session_id=session_id,
            provider=self.provider_name,
            provider_model=self.provider_model,
            conversation_history_pairs=self.conversation_history_pairs,
            moonraker_reachable=moonraker_reachable,
            klipper_reachable=klipper_reachable,
            expires_at=session.expires_at,
            features=[
                "diagnostics",
                "config-assistant",
                "current-config-inspection",
                "single-question-input",
                "read-only-mode",
                "host-log-collection",
                "systemd-diagnostics",
                "printer-profile",
                "addon-detection",
                "typed-findings",
                "local-workflows",
                "conversation-history",
                "new-chat",
                "intent-routing",
                "context-gated-flows",
            ],
            printer_profile=PrinterProfileSummary.model_validate(self.workflow_context.profile.to_summary()),
        )

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        session = self.sessions.get(payload.session_id)
        if not session:
            logger.warning("Rejected chat for invalid or expired session session_id=%s", payload.session_id)
            raise ValueError("Invalid or expired session.")

        thread_id = payload.thread_id or str(uuid4())
        conversation_context = _format_conversation_context(
            payload.history,
            max_pairs=self.conversation_history_pairs,
        )
        classification_message = _build_contextual_classification_message(payload.message, conversation_context)
        chat_intent = await self._classify_chat_intent(payload.message, classification_message=classification_message)
        route = route_for_intent(chat_intent)
        request_artifacts = _build_chat_artifacts(payload.message, route, payload.artifacts)
        state = {
            "session_id": payload.session_id,
            "thread_id": thread_id,
            "user_message": payload.message,
            "conversation_context": conversation_context,
            "artifacts": [artifact.model_dump() for artifact in request_artifacts],
            "chat_intent": chat_intent.model_dump(),
        }
        graph = self.config_graph if route == "config" else self.diagnosis_graph
        config = {"configurable": {"thread_id": f"{route}:{thread_id}"}}
        logger.info(
            "Chat request session_id=%s thread_id=%s route=%s message_chars=%s artifacts=%s",
            payload.session_id,
            thread_id,
            route,
            len(payload.message),
            len(request_artifacts),
        )
        try:
            result = await graph.ainvoke(
                state,
                config=config,
                context=self.workflow_context,
            )
        except Exception:
            logger.exception(
                "Chat workflow failed session_id=%s thread_id=%s route=%s",
                payload.session_id,
                thread_id,
                route,
            )
            raise

        findings = [IssueFinding.model_validate(item) for item in result.get("findings", [])]
        config_proposals = [ConfigProposal.model_validate(item) for item in result.get("config_proposals", [])]
        patch_proposals = [PatchProposal.model_validate(item) for item in result.get("patch_proposals", [])]
        source_citations = [SourceCitation.model_validate(item) for item in result.get("source_citations", [])]
        logger.info(
            "Chat response session_id=%s thread_id=%s route=%s findings=%s config_proposals=%s patch_proposals=%s source_citations=%s moonraker_reachable=%s",
            payload.session_id,
            thread_id,
            route,
            len(findings),
            len(config_proposals),
            len(patch_proposals),
            len(source_citations),
            result.get("moonraker_reachable", False),
        )
        return ChatResponse(
            session_id=payload.session_id,
            thread_id=thread_id,
            response=result.get("response_text", "No response generated."),
            findings=findings,
            next_actions=result.get("next_actions", []),
            config_proposals=config_proposals,
            patch_proposals=patch_proposals,
            source_citations=source_citations,
            provider=self.provider_name,
            moonraker_reachable=result.get("moonraker_reachable", False),
        )

    async def _classify_chat_intent(self, message: str, *, classification_message: str | None = None) -> ChatIntentOutput:
        deterministic = classify_deterministic_intent(message)

        intent_router = getattr(self.workflow_context, "intent_router", None)
        if intent_router is None:
            return deterministic

        try:
            routed = ChatIntentOutput.model_validate(await intent_router.classify(classification_message or message))
        except Exception:
            logger.exception("Intent routing failed; falling back to deterministic route.")
            return deterministic

        if routed.confidence <= 0:
            return deterministic
        return routed


def _build_chat_artifacts(
    message: str,
    route: str,
    request_artifacts: list[ArtifactInput],
) -> list[ArtifactInput]:
    artifacts = list(request_artifacts)
    inline_artifact = _infer_inline_question_artifact(message, route)
    if inline_artifact is not None:
        artifacts.append(inline_artifact)
    return artifacts


def _format_conversation_context(history: list[ChatHistoryMessage], *, max_pairs: int) -> str:
    max_messages = max(0, max_pairs) * 2
    if max_messages <= 0:
        return ""

    lines: list[str] = []
    for item in history[-max_messages:]:
        text = item.text.strip()
        if not text:
            continue
        if len(text) > _MAX_HISTORY_CHARS_PER_MESSAGE:
            text = f"{text[:_MAX_HISTORY_CHARS_PER_MESSAGE]}\n...[truncated]..."
        role = "User" if item.role == "user" else "KlippyAI"
        lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def _build_contextual_classification_message(message: str, conversation_context: str) -> str:
    if not conversation_context:
        return message
    return (
        "Recent conversation:\n"
        f"{conversation_context}\n\n"
        "Current user message:\n"
        f"{message}\n\n"
        "Classify the current user message. Use the recent conversation only to resolve follow-ups like "
        "'do that', 'yes', 'show me that', or 'continue'."
    )


def _infer_inline_question_artifact(message: str, route: str) -> ArtifactInput | None:
    normalized = message.strip()
    if not normalized:
        return None

    line_count = normalized.count("\n") + 1
    looks_structured = bool(_CONFIG_SECTION_PATTERN.search(normalized) or _LOG_LINE_PATTERN.search(normalized))
    if not looks_structured and line_count < 8:
        return None

    kind = "config_snippet" if _CONFIG_SECTION_PATTERN.search(normalized) else "notes"
    if route == "diagnostics" and _LOG_LINE_PATTERN.search(normalized):
        kind = "system_log"

    return ArtifactInput(
        kind=kind,
        label="question-context",
        content=normalized,
    )
