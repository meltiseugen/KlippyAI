from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from klippyai_agent.hostlogs import HostLogCollector
from klippyai_agent.hostsystem import HostSystemCollector
from klippyai_agent.moonraker import MoonrakerClient, MoonrakerError
from klippyai_agent.printerconfig import ConfigSnapshot
from klippyai_agent.schemas import ArtifactInput, IssueFinding, Severity


@dataclass(slots=True)
class DiagnosticsSnapshot:
    moonraker_reachable: bool
    moonraker_info: dict[str, Any] | None
    artifacts: list[ArtifactInput]
    notes: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        sections: list[str] = []

        if self.moonraker_info:
            sections.append(f"Moonraker server info:\n{self.moonraker_info}")
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))

        if self.artifacts:
            artifact_blocks = [
                f"[{artifact.kind}] {artifact.label}\n{artifact.prompt_excerpt()}"
                for artifact in self.artifacts
            ]
            sections.append("Artifacts:\n" + "\n\n".join(artifact_blocks))

        return "\n\n".join(sections) if sections else "No runtime context collected."


class DiagnosticsCollector:
    def __init__(
        self,
        moonraker: MoonrakerClient,
        *,
        host_logs: HostLogCollector | None = None,
        host_system: HostSystemCollector | None = None,
    ) -> None:
        self._moonraker = moonraker
        self._host_logs = host_logs
        self._host_system = host_system

    async def ping(self) -> bool:
        return await self._moonraker.ping()

    async def collect(self, artifacts: list[ArtifactInput]) -> DiagnosticsSnapshot:
        notes: list[str] = []
        moonraker_info: dict[str, Any] | None = None
        reachable = False
        snapshot_artifacts = list(artifacts)

        try:
            moonraker_info = await self._moonraker.get_server_info()
            reachable = True
        except MoonrakerError as exc:
            notes.append(str(exc))

        if self._host_logs is not None:
            host_artifacts, host_notes = self._host_logs.collect()
            snapshot_artifacts.extend(host_artifacts)
            notes.extend(host_notes)

        if self._host_system is not None:
            system_artifacts, system_notes = await asyncio.to_thread(self._host_system.collect)
            snapshot_artifacts.extend(system_artifacts)
            notes.extend(system_notes)

        return DiagnosticsSnapshot(
            moonraker_reachable=reachable,
            moonraker_info=moonraker_info,
            artifacts=snapshot_artifacts,
            notes=notes,
        )


class RuleEngine:
    _PATTERNS: tuple[tuple[str, re.Pattern[str], Severity, str, str], ...] = (
        (
            "mcu_timer_too_close",
            re.compile(r"Timer too close", re.IGNORECASE),
            "high",
            "MCU timing is too tight for the current motion or host scheduling.",
            "Reduce acceleration/velocity peaks, inspect host load, and verify MCU link stability.",
        ),
        (
            "mcu_connect_failure",
            re.compile(r"mcu .*Unable to connect|Unable to connect to MCU", re.IGNORECASE),
            "critical",
            "Klipper cannot connect to one of the configured MCU devices.",
            "Verify USB or CAN connectivity, the serial path, power state, and firmware flashing target.",
        ),
        (
            "config_file_missing",
            re.compile(r"Unable to open config file|No such file or directory", re.IGNORECASE),
            "high",
            "A referenced configuration include or file is missing.",
            "Check include paths, recent file moves, and whether generated files exist on disk.",
        ),
        (
            "adc_out_of_range",
            re.compile(r"ADC out of range", re.IGNORECASE),
            "high",
            "A temperature sensor reading is outside the safe range.",
            "Inspect thermistor wiring, sensor type configuration, and any intermittent connector issues.",
        ),
        (
            "bltouch_probe_failure",
            re.compile(r"BLTouch failed|probe failed", re.IGNORECASE),
            "medium",
            "The probe did not deploy or trigger as expected.",
            "Check BLTouch wiring, pin assignments, probe offsets, and mechanical interference.",
        ),
        (
            "systemd_service_failed",
            re.compile(
                r"ActiveState=failed|Result=exit-code|Result=signal|Start request repeated too quickly",
                re.IGNORECASE,
            ),
            "critical",
            "A required printer host service is failing under systemd.",
            "Inspect the paired journalctl artifact, correct the startup failure, and restart the affected service.",
        ),
    )

    def analyze(
        self,
        artifacts: list[ArtifactInput],
        *,
        config_snapshot: ConfigSnapshot | None = None,
    ) -> list[IssueFinding]:
        findings: list[IssueFinding] = []
        seen_codes: set[tuple[str, str]] = set()

        for artifact in artifacts:
            for code, pattern, severity, summary, fix in self._PATTERNS:
                match = pattern.search(artifact.content)
                if not match:
                    continue

                key = (code, artifact.label)
                if key in seen_codes:
                    continue
                seen_codes.add(key)

                evidence = artifact.content[max(0, match.start() - 80) : match.end() + 160].strip()
                findings.append(
                    IssueFinding(
                        code=code,
                        severity=severity,
                        source=artifact.label,
                        summary=summary,
                        evidence=evidence,
                        proposed_fix=fix,
                    )
                )

        if config_snapshot is not None:
            findings.extend(self._analyze_config_snapshot(config_snapshot))

        findings.sort(key=lambda finding: self._severity_rank(finding.severity), reverse=True)
        return findings

    @staticmethod
    def _severity_rank(severity: str) -> int:
        ranks = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return ranks.get(severity, 0)

    def _analyze_config_snapshot(self, config_snapshot: ConfigSnapshot) -> list[IssueFinding]:
        findings: list[IssueFinding] = []

        for placeholder in config_snapshot.placeholders[:8]:
            section_detail = f" in section [{placeholder.section}]" if placeholder.section else ""
            option_detail = f" for option '{placeholder.option}'" if placeholder.option else ""
            findings.append(
                IssueFinding(
                    code="config_placeholder_value",
                    severity="high",
                    source=f"{placeholder.path}:{placeholder.line_number}",
                    summary=(
                        f"Placeholder value {placeholder.value} is still active{section_detail}{option_detail}, "
                        "which can prevent Klipper from loading the config."
                    ),
                    evidence=placeholder.line_text,
                    proposed_fix=(
                        f"Replace {placeholder.value} with the real hardware value in "
                        f"{placeholder.path}:{placeholder.line_number} and restart Klipper."
                    ),
                )
            )

        return findings
