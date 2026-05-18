from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from klippyai_agent.schemas import ArtifactInput


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class SystemCommandRunner:
    def __init__(self, timeout_seconds: float = 6.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, command: tuple[str, ...]) -> CommandResult:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )


@dataclass(frozen=True, slots=True)
class ServiceUnit:
    display_name: str
    unit_name: str


class HostSystemCollector:
    _STATUS_PROPERTIES = (
        "Id",
        "LoadState",
        "ActiveState",
        "SubState",
        "UnitFileState",
        "Result",
        "ExecMainCode",
        "ExecMainStatus",
        "MainPID",
        "NRestarts",
        "FragmentPath",
        "ActiveEnterTimestamp",
        "StateChangeTimestamp",
    )

    def __init__(
        self,
        *,
        moonraker_service_name: str = "moonraker.service",
        klipper_service_name: str = "klipper.service",
        journal_lines: int = 200,
        status_artifact_char_limit: int = 6000,
        journal_artifact_char_limit: int = 16000,
        runner: SystemCommandRunner | None = None,
    ) -> None:
        self._services = (
            ServiceUnit(display_name="Moonraker", unit_name=moonraker_service_name),
            ServiceUnit(display_name="Klipper", unit_name=klipper_service_name),
        )
        self._journal_lines = journal_lines
        self._status_artifact_char_limit = status_artifact_char_limit
        self._journal_artifact_char_limit = journal_artifact_char_limit
        self._runner = runner or SystemCommandRunner()

    def collect(self) -> tuple[list[ArtifactInput], list[str]]:
        artifacts: list[ArtifactInput] = []
        notes: list[str] = []

        for service in self._services:
            status_artifact, status_note = self._collect_service_status(service)
            if status_artifact is not None:
                artifacts.append(status_artifact)
            if status_note:
                self._append_unique(notes, status_note)

            journal_artifact, journal_note = self._collect_service_journal(service)
            if journal_artifact is not None:
                artifacts.append(journal_artifact)
            if journal_note:
                self._append_unique(notes, journal_note)

        return artifacts, notes

    def _collect_service_status(self, service: ServiceUnit) -> tuple[ArtifactInput | None, str | None]:
        command = (
            "systemctl",
            "show",
            "--no-pager",
            "--property",
            ",".join(self._STATUS_PROPERTIES),
            service.unit_name,
        )
        try:
            result = self._runner.run(command)
        except FileNotFoundError:
            return None, "systemctl is not available on this host."
        except subprocess.TimeoutExpired:
            return None, f"Timed out while collecting systemctl status for {service.unit_name}."

        if result.returncode != 0:
            message = result.stderr or result.stdout or "Unknown systemctl failure."
            return None, f"systemctl show failed for {service.unit_name}: {message}"

        if not result.stdout:
            return None, f"systemctl show returned no data for {service.unit_name}."

        content = self._render_status_artifact(service, result.stdout)
        return (
            ArtifactInput(
                kind="system_log",
                label=f"systemctl show {service.unit_name}",
                content=self._clip_text(content, 39_000, self._status_artifact_char_limit),
            ),
            f"Collected systemctl status for {service.unit_name}.",
        )

    def _collect_service_journal(self, service: ServiceUnit) -> tuple[ArtifactInput | None, str | None]:
        command = (
            "journalctl",
            "--unit",
            service.unit_name,
            "--no-pager",
            "--output=short-iso",
            "-n",
            str(self._journal_lines),
        )
        try:
            result = self._runner.run(command)
        except FileNotFoundError:
            return None, "journalctl is not available on this host."
        except subprocess.TimeoutExpired:
            return None, f"Timed out while collecting journalctl output for {service.unit_name}."

        if result.returncode != 0:
            message = result.stderr or result.stdout or "Unknown journalctl failure."
            return None, f"journalctl failed for {service.unit_name}: {message}"

        if not result.stdout:
            return None, f"journalctl returned no lines for {service.unit_name}."

        content = self._render_journal_artifact(service, result.stdout)
        return (
            ArtifactInput(
                kind="system_log",
                label=f"journalctl {service.unit_name}",
                content=self._clip_text(content, 39_000, self._journal_artifact_char_limit),
            ),
            f"Collected the last {self._journal_lines} journal lines for {service.unit_name}.",
        )

    def _render_status_artifact(self, service: ServiceUnit, body: str) -> str:
        return (
            f"Host service status: {service.display_name}\n"
            f"Unit: {service.unit_name}\n"
            f"Command: {self._format_command(('systemctl', 'show', service.unit_name))}\n\n"
            f"{body}"
        )

    def _render_journal_artifact(self, service: ServiceUnit, body: str) -> str:
        return (
            f"Host service journal: {service.display_name}\n"
            f"Unit: {service.unit_name}\n"
            f"Selection: last {self._journal_lines} journal lines\n"
            f"Command: {self._format_command(('journalctl', '--unit', service.unit_name, '-n', str(self._journal_lines)))}\n\n"
            f"{body}"
        )

    @staticmethod
    def _clip_text(text: str, absolute_limit: int, target_limit: int) -> str:
        limit = min(absolute_limit, target_limit)
        if len(text) <= limit:
            return text

        head = max((limit - 32) // 2, 0)
        tail = max(limit - head - 17, 0)
        return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"

    @staticmethod
    def _format_command(command: tuple[str, ...]) -> str:
        return shlex.join(command)

    @staticmethod
    def _append_unique(items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)
