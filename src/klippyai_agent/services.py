from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from uuid import uuid4

from klippyai_agent.printerconfig import looks_like_config_request
from klippyai_agent.schemas import (
    ArtifactInput,
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    ConfigProposal,
    IssueFinding,
    PatchProposal,
    PrinterProfileSummary,
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


@dataclass(slots=True)
class ChatService:
    provider_name: str
    root_path: str
    diagnosis_graph: object
    config_graph: object
    workflow_context: WorkflowContext
    sessions: InMemorySessionStore

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
        logger.info(
            "Bootstrap session_id=%s moonraker_reachable=%s profile=%s",
            session_id,
            moonraker_reachable,
            self.workflow_context.profile.summary_label() or "unavailable",
        )
        return BootstrapResponse(
            session_id=session_id,
            provider=self.provider_name,
            moonraker_reachable=moonraker_reachable,
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
                "langgraph-checkpoints",
                "conversation-persistence",
                "conversation-history",
                "new-chat",
            ],
            printer_profile=PrinterProfileSummary.model_validate(self.workflow_context.profile.to_summary()),
        )

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        session = self.sessions.get(payload.session_id)
        if not session:
            logger.warning("Rejected chat for invalid or expired session session_id=%s", payload.session_id)
            raise ValueError("Invalid or expired session.")

        thread_id = payload.thread_id or str(uuid4())
        route = "config" if looks_like_config_request(payload.message) else "diagnostics"
        request_artifacts = _build_chat_artifacts(payload.message, route, payload.artifacts)
        state = {
            "session_id": payload.session_id,
            "thread_id": thread_id,
            "user_message": payload.message,
            "artifacts": [artifact.model_dump() for artifact in request_artifacts],
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
        logger.info(
            "Chat response session_id=%s thread_id=%s route=%s findings=%s config_proposals=%s patch_proposals=%s moonraker_reachable=%s",
            payload.session_id,
            thread_id,
            route,
            len(findings),
            len(config_proposals),
            len(patch_proposals),
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
            provider=self.provider_name,
            moonraker_reachable=result.get("moonraker_reachable", False),
        )


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
