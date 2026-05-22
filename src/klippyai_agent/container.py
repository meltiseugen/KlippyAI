from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from klippyai_agent.diagnostics import DiagnosticsCollector, RuleEngine
from klippyai_agent.hostlogs import HostLogCollector
from klippyai_agent.hostsystem import HostSystemCollector, SystemCommandRunner
from klippyai_agent.llm import build_config_provider, build_diagnosis_provider
from klippyai_agent.moonraker import MoonrakerClient
from klippyai_agent.printerconfig import ConfigCollector
from klippyai_agent.printerprofile import build_profile_from_settings
from klippyai_agent.services import ChatService
from klippyai_agent.sessions import InMemorySessionStore
from klippyai_agent.settings import Settings
from klippyai_agent.workflows import WorkflowContext, build_config_graph, build_diagnosis_graph


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    moonraker: MoonrakerClient
    sessions: InMemorySessionStore
    chat_service: ChatService

    async def aclose(self) -> None:
        await self.moonraker.aclose()


def build_container(settings: Settings, checkpointer: Any) -> AppContainer:
    moonraker = MoonrakerClient(settings.moonraker_url)
    host_logs = None
    if settings.collect_host_logs:
        host_logs = HostLogCollector(
            settings.printer_data_root,
            logs_dir_path=settings.logs_dir_path,
            default_tail_lines=settings.log_tail_lines_default,
            tail_lines_by_log=settings.log_tail_lines_overrides,
            excluded_logs=settings.excluded_logs,
            artifact_char_limit=settings.log_artifact_char_limit,
        )
    host_system = None
    if settings.collect_systemd_diagnostics:
        host_system = HostSystemCollector(
            moonraker_service_name=settings.moonraker_service_name,
            klipper_service_name=settings.klipper_service_name,
            journal_lines=settings.journal_lines,
            status_artifact_char_limit=settings.system_status_artifact_char_limit,
            journal_artifact_char_limit=settings.journal_artifact_char_limit,
            runner=SystemCommandRunner(timeout_seconds=settings.system_command_timeout_seconds),
        )
    collector = DiagnosticsCollector(
        moonraker,
        host_logs=host_logs,
        host_system=host_system,
    )
    rules = RuleEngine()
    diagnosis_provider = build_diagnosis_provider(settings)
    config_provider = build_config_provider(settings)
    config_collector = ConfigCollector(
        settings.printer_data_root,
        root_config_name=settings.config_root_file,
        ignore_globs=settings.config_ignore_globs,
    )
    profile = build_profile_from_settings(settings)
    workflow_context = WorkflowContext(
        collector=collector,
        rules=rules,
        llm=diagnosis_provider,
        config_collector=config_collector,
        config_llm=config_provider,
        host_logs=host_logs,
        profile=profile,
    )
    diagnosis_graph = build_diagnosis_graph(checkpointer)
    config_graph = build_config_graph(checkpointer)
    sessions = InMemorySessionStore(settings.session_ttl_seconds)
    chat_service = ChatService(
        provider_name=diagnosis_provider.name,
        root_path=settings.root_path.rstrip("/"),
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=workflow_context,
        sessions=sessions,
    )
    return AppContainer(
        settings=settings,
        moonraker=moonraker,
        sessions=sessions,
        chat_service=chat_service,
    )
