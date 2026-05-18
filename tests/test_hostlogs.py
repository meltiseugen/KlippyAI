from __future__ import annotations

from pathlib import Path

import pytest

from klippyai_agent.diagnostics import DiagnosticsCollector, RuleEngine
from klippyai_agent.hostlogs import HostLogCollector


def test_host_log_collector_reads_active_and_archived_logs(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)

    archived = logs_dir / "klippy.log.2026-05-18_08-00-00"
    archived.write_text("Start printer at archived-session\nArchived context\n", encoding="utf-8")

    active = logs_dir / "klippy.log"
    active.write_text(
        "Start printer at old-session\nOld lines\n"
        "Start printer at current-session\nMCU 'mcu' shutdown: Timer too close\n",
        encoding="utf-8",
    )

    collector = HostLogCollector(
        tmp_path / "printer_data",
        max_files_per_family=2,
        active_tail_bytes=4096,
        rotated_tail_bytes=4096,
    )
    artifacts, notes = collector.collect()

    assert any(artifact.label == "klippy.log (current)" for artifact in artifacts)
    assert any("Focus mode" in artifact.content for artifact in artifacts)
    assert any("current-session" in artifact.content for artifact in artifacts)
    assert all("old-session" not in artifact.content for artifact in artifacts if artifact.label == "klippy.log (current)")
    assert any("Loaded 2 Klippy log file(s)" in note for note in notes)


class _FakeMoonraker:
    async def ping(self) -> bool:
        return True

    async def get_server_info(self) -> dict[str, object]:
        return {"klippy_connected": True}


@pytest.mark.asyncio
async def test_diagnostics_collector_merges_host_logs_into_snapshot(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "klippy.log").write_text(
        "Start printer at session\nMCU 'mcu' shutdown: Timer too close\n",
        encoding="utf-8",
    )

    host_logs = HostLogCollector(tmp_path / "printer_data", max_files_per_family=1)
    collector = DiagnosticsCollector(_FakeMoonraker(), host_logs=host_logs)

    snapshot = await collector.collect([])
    findings = RuleEngine().analyze(snapshot.artifacts)

    assert snapshot.moonraker_reachable is True
    assert any(artifact.label == "klippy.log (current)" for artifact in snapshot.artifacts)
    assert findings
    assert findings[0].code == "mcu_timer_too_close"
