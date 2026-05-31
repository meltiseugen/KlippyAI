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

    async def ping_printer(self) -> bool:
        return True


class _FakeIntentRouter:
    name = "fake"

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[str] = []

    async def classify(self, message: str) -> dict[str, object]:
        self.calls.append(message)
        return self.result


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
            profile=PrinterProfile(firmware_flavor="Kalico"),
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
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "generate_config"
    assert config_graph.calls[0]["state"]["chat_intent"]["needs_logs"] is False


@pytest.mark.asyncio
async def test_chat_service_routes_config_lookup_request_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph(
        "config",
        {
            "response_text": "I found 1 active [extruder] section in the current config tree.",
            "config_proposals": [],
        },
    )
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Where do I have the extruder defined?",
            artifacts=[],
        )
    )

    assert "extruder" in response.response
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_lookup"


@pytest.mark.asyncio
async def test_chat_service_routes_macro_name_correction_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "SFS_ENABLE is defined in filament.cfg:1."})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="I mean SFS_ENABLE",
            artifacts=[],
        )
    )

    assert "SFS_ENABLE" in response.response
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_lookup"


@pytest.mark.asyncio
async def test_chat_service_routes_problem_language_to_diagnostics_with_logs_enabled() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Why is SFS_ENABLE failing?",
            artifacts=[],
        )
    )

    assert diagnosis_graph.calls
    assert not config_graph.calls
    assert diagnosis_graph.calls[0]["state"]["chat_intent"]["intent"] == "diagnose_issue"
    assert diagnosis_graph.calls[0]["state"]["chat_intent"]["needs_logs"] is True


@pytest.mark.asyncio
async def test_chat_service_uses_llm_intent_router_for_ambiguous_requests() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "config_explain",
            "target": "SFS_ENABLE",
            "target_section": "gcode_macro SFS_ENABLE",
            "needs_logs": False,
            "confidence": 0.91,
            "rationale": "The user asked to understand a macro.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Can you help me with SFS_ENABLE?",
            artifacts=[],
        )
    )

    assert intent_router.calls == ["Can you help me with SFS_ENABLE?"]
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_explain"


@pytest.mark.asyncio
async def test_chat_service_prefers_intent_router_over_deterministic_guess() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "diagnose_issue",
            "target": "extruder",
            "needs_logs": True,
            "confidence": 0.92,
            "rationale": "The user is asking about a failure.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Where do I have the extruder defined?",
            artifacts=[],
        )
    )

    assert intent_router.calls == ["Where do I have the extruder defined?"]
    assert diagnosis_graph.calls
    assert not config_graph.calls


@pytest.mark.asyncio
async def test_chat_service_promotes_structured_question_text_into_artifact() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=_FakeGraph("config", {"response_text": "config"}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message=(
                "Why is Klipper shut down?\n\n"
                "Start printer at Wed May 21 10:00:00 2026\n"
                "MCU 'mcu' shutdown: Timer too close\n"
                "Once the underlying issue is corrected, use the\n"
                '  "FIRMWARE_RESTART" command to reset the firmware.\n'
            ),
            artifacts=[],
        )
    )

    state = diagnosis_graph.calls[0]["state"]
    artifacts = state["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "system_log"
    assert artifacts[0]["label"] == "question-context"


@pytest.mark.asyncio
async def test_bootstrap_includes_printer_profile_summary() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()
    service = ChatService(
        provider_name="stub",
        provider_model="stub-model",
        root_path="",
        diagnosis_graph=_FakeGraph("diagnostics", {}),
        config_graph=_FakeGraph("config", {}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.bootstrap(session.session_id)

    assert response.moonraker_reachable is True
    assert response.klipper_reachable is True
    assert response.provider_model == "stub-model"
    assert response.printer_profile is not None
    assert response.printer_profile.firmware_flavor == "Kalico"
    assert "read-only-mode" in response.features
