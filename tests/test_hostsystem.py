from __future__ import annotations

import subprocess

from klippyai_agent.hostsystem import CommandResult, HostSystemCollector


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> CommandResult:
        self.commands.append(command)
        unit_name = command[command.index("--unit") + 1] if "--unit" in command else command[-1]

        if command[0] == "systemctl":
            return CommandResult(
                command=command,
                returncode=0,
                stdout=(
                    f"Id={unit_name}\n"
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    "SubState=running\n"
                    "Result=success"
                ),
                stderr="",
            )

        return CommandResult(
            command=command,
            returncode=0,
            stdout=f"2026-05-18T10:11:12+00:00 host {unit_name}[123]: started cleanly",
            stderr="",
        )


class _FailingRunner:
    def run(self, command: tuple[str, ...]) -> CommandResult:
        if command[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        raise subprocess.TimeoutExpired(command, 3)


def test_host_system_collector_collects_service_status_and_journal() -> None:
    runner = _FakeRunner()
    collector = HostSystemCollector(
        moonraker_service_name="moonraker.service",
        klipper_service_name="klipper.service",
        journal_lines=25,
        runner=runner,
    )

    artifacts, notes = collector.collect()

    assert len(artifacts) == 4
    assert any(artifact.label == "systemctl show moonraker.service" for artifact in artifacts)
    assert any(artifact.label == "journalctl moonraker.service" for artifact in artifacts)
    assert any("Collected systemctl status for moonraker.service." == note for note in notes)
    assert any("Collected the last 25 journal lines for klipper.service." == note for note in notes)
    assert runner.commands[0][0] == "systemctl"
    assert runner.commands[1][0] == "journalctl"


def test_host_system_collector_reports_missing_commands_and_timeouts() -> None:
    collector = HostSystemCollector(runner=_FailingRunner())
    artifacts, notes = collector.collect()

    assert artifacts == []
    assert any("systemctl is not available on this host." == note for note in notes)
    assert any("Timed out while collecting journalctl output for moonraker.service." == note for note in notes)
