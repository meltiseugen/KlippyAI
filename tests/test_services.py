from __future__ import annotations

from types import SimpleNamespace

import pytest

from klippyai_agent.printerprofile import PrinterProfile
from klippyai_agent.schemas import ChatRequest
from klippyai_agent.services import ChatService
from klippyai_agent.sessions import InMemorySessionStore


class _FakeGraph:
    def __init__(self, name: str, result: dict[str, object]) -> None:
        self.name = name
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, state: dict[str, object], **kwargs: object) -> dict[str, object]:
        self.calls.append({"state": state, **kwargs})
        return self.result


class _FakeCollector:
    async def ping(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_chat_service_routes_config_request_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph(
        "config",
        {
            "response_text": "config",
            "config_proposals": [
                {
                    "feature": "fan",
                    "title": "Fan config",
                    "target_file": "klippyai/fan.cfg",
                    "config": "[fan]\npin: PA1\n",
                    "rationale": "test",
                    "assumptions": [],
                    "warnings": [],
                }
            ],
        },
    )
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico", kinematics="corexy"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Generate me a config for a fan",
            artifacts=[],
        )
    )

    assert response.response == "config"
    assert len(response.config_proposals) == 1
    assert not diagnosis_graph.calls
    assert config_graph.calls


@pytest.mark.asyncio
async def test_bootstrap_includes_printer_profile_summary() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=_FakeGraph("diagnostics", {}),
        config_graph=_FakeGraph("config", {}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico", kinematics="corexy"),
        ),
        sessions=sessions,
    )

    response = await service.bootstrap(session.session_id)

    assert response.moonraker_reachable is True
    assert response.printer_profile is not None
    assert response.printer_profile.firmware_flavor == "Kalico"
    assert response.printer_profile.kinematics == "corexy"
    assert "read-only-mode" in response.features
