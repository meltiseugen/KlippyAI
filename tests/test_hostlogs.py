from __future__ import annotations

from pathlib import Path

import pytest

from klippyai_agent.diagnostics import DiagnosticsCollector, RuleEngine
from klippyai_agent.hostlogs import HostLogCollector


def test_host_log_collector_reads_all_current_log_files_and_tails_last_lines(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)

    active = logs_dir / "klippy.log"
    active.write_text("\n".join(f"line {index}" for index in range(1, 151)), encoding="utf-8")
    extra = logs_dir / "crowsnest.log"
    extra.write_text("cam line 1\ncam line 2\n", encoding="utf-8")
    archived = logs_dir / "klippy.log.2026-05-18_08-00-00"
    archived.write_text("archived line\n", encoding="utf-8")

    collector = HostLogCollector(
        tmp_path / "printer_data",
        default_tail_lines=100,
    )
    artifacts, notes = collector.collect()

    assert any(artifact.label == "klippy.log" for artifact in artifacts)
    assert any(artifact.label == "crowsnest.log" for artifact in artifacts)
    assert all("klippy.log.2026-05-18_08-00-00" != artifact.label for artifact in artifacts)
    klippy_artifact = next(artifact for artifact in artifacts if artifact.label == "klippy.log")
    assert "line 150" in klippy_artifact.content
    assert "line 51" in klippy_artifact.content
    assert "line 50" not in klippy_artifact.content
    assert any("Loaded 2 current log file(s)" in note for note in notes)


def test_host_log_collector_supports_per_log_tail_lengths(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "klippy.log").write_text("\n".join(f"klippy {index}" for index in range(1, 151)), encoding="utf-8")
    (logs_dir / "moonraker.log").write_text("\n".join(f"moonraker {index}" for index in range(1, 251)), encoding="utf-8")

    collector = HostLogCollector(
        tmp_path / "printer_data",
        default_tail_lines=100,
        tail_lines_by_log={"klippy": 40, "moonraker": 200},
    )
    artifacts, _notes = collector.collect()

    klippy_artifact = next(artifact for artifact in artifacts if artifact.label == "klippy.log")
    moonraker_artifact = next(artifact for artifact in artifacts if artifact.label == "moonraker.log")
    assert "Selection: last 40 line(s)" in klippy_artifact.content
    assert "klippy 111" in klippy_artifact.content
    assert "klippy 110" not in klippy_artifact.content
    assert "Selection: last 200 line(s)" in moonraker_artifact.content
    assert "moonraker 51" in moonraker_artifact.content
    assert "moonraker 50" not in moonraker_artifact.content


def test_host_log_collector_detects_klippyai_runtime_logs(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "klippyai.log").write_text(
        "2026-05-19 12:00:00 INFO [klippyai_agent.bootstrap] Starting KlippyAI\n"
        "2026-05-19 12:00:01 INFO [klippyai_agent.app] Application startup complete.\n",
        encoding="utf-8",
    )

    collector = HostLogCollector(tmp_path / "printer_data")
    artifacts, notes = collector.collect()

    assert any(artifact.label == "klippyai.log" for artifact in artifacts)
    assert any("Host log: KlippyAI" in artifact.content for artifact in artifacts)
    assert any("Loaded 1 current log file(s)" in note for note in notes)


def test_host_log_collector_skips_excluded_logs_by_name_stem_and_glob(tmp_path: Path) -> None:
    logs_dir = tmp_path / "printer_data" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "klippy.log").write_text("klippy line\n", encoding="utf-8")
    (logs_dir / "klippyai.log").write_text("agent line\n", encoding="utf-8")
    (logs_dir / "crowsnest.log").write_text("camera line\n", encoding="utf-8")
    (logs_dir / "service_debug.log").write_text("debug line\n", encoding="utf-8")

    collector = HostLogCollector(
        tmp_path / "printer_data",
        excluded_logs=["klippyai.log", "crowsnest", "*_debug.log"],
    )
    artifacts, notes = collector.collect()

    labels = {artifact.label for artifact in artifacts}
    assert labels == {"klippy.log"}
    assert any("Loaded 1 current log file(s)" in note for note in notes)


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

    host_logs = HostLogCollector(tmp_path / "printer_data")
    collector = DiagnosticsCollector(_FakeMoonraker(), host_logs=host_logs)

    snapshot = await collector.collect([])
    findings = RuleEngine().analyze(snapshot.artifacts)

    assert snapshot.moonraker_reachable is True
    assert any(artifact.label == "klippy.log" for artifact in snapshot.artifacts)
    assert findings
    assert findings[0].code == "mcu_timer_too_close"
