from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from klippyai_agent.printerconfig import looks_like_config_request
from klippyai_agent.schemas import (
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    ConfigProposal,
    IssueFinding,
    PatchProposal,
    UiSessionResponse,
)
from klippyai_agent.sessions import InMemorySessionStore
from klippyai_agent.workflows import WorkflowContext


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
        return UiSessionResponse(
            session_id=session.session_id,
            embed_path=f"{self.root_path}/embed?session={session.session_id}" if self.root_path else f"/embed?session={session.session_id}",
            expires_at=session.expires_at,
        )

    async def bootstrap(self, session_id: str) -> BootstrapResponse:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError("Invalid or expired session.")

        moonraker_reachable = await self.workflow_context.collector.ping()
        return BootstrapResponse(
            session_id=session_id,
            provider=self.provider_name,
            moonraker_reachable=moonraker_reachable,
            expires_at=session.expires_at,
            features=[
                "diagnostics",
                "config-assistant",
                "current-config-inspection",
                "artifact-paste",
                "host-log-collection",
                "systemd-diagnostics",
                "typed-findings",
                "langgraph-checkpoints",
            ],
        )

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        session = self.sessions.get(payload.session_id)
        if not session:
            raise ValueError("Invalid or expired session.")

        thread_id = payload.thread_id or str(uuid4())
        state = {
            "session_id": payload.session_id,
            "thread_id": thread_id,
            "user_message": payload.message,
            "artifacts": [artifact.model_dump() for artifact in payload.artifacts],
        }
        route = "config" if looks_like_config_request(payload.message) else "diagnostics"
        graph = self.config_graph if route == "config" else self.diagnosis_graph
        config = {"configurable": {"thread_id": f"{route}:{thread_id}"}}
        result = await graph.ainvoke(
            state,
            config=config,
            context=self.workflow_context,
        )

        findings = [IssueFinding.model_validate(item) for item in result.get("findings", [])]
        config_proposals = [ConfigProposal.model_validate(item) for item in result.get("config_proposals", [])]
        patch_proposals = [PatchProposal.model_validate(item) for item in result.get("patch_proposals", [])]
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
