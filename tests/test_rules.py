from pathlib import Path

from klippyai_agent.diagnostics import RuleEngine
from klippyai_agent.printerconfig import ConfigCollector
from klippyai_agent.schemas import ArtifactInput


def test_timer_too_close_is_detected() -> None:
    engine = RuleEngine()
    findings = engine.analyze(
        [
            ArtifactInput(
                kind="klippy_log",
                label="klippy.log",
                content="MCU 'mcu' shutdown: Timer too close",
            )
        ]
    )
    assert findings
    assert findings[0].code == "mcu_timer_too_close"


def test_missing_config_file_is_detected() -> None:
    engine = RuleEngine()
    findings = engine.analyze(
        [
            ArtifactInput(
                kind="klippy_log",
                label="klippy.log",
                content="Unable to open config file /home/pi/printer_data/config/extras/input_shaper.cfg",
            )
        ]
    )
    assert findings
    assert findings[0].code == "config_file_missing"


def test_failed_systemd_service_is_detected() -> None:
    engine = RuleEngine()
    findings = engine.analyze(
        [
            ArtifactInput(
                kind="system_log",
                label="systemctl show klipper.service",
                content="Id=klipper.service\nActiveState=failed\nResult=exit-code",
            )
        ]
    )
    assert findings
    assert findings[0].code == "systemd_service_failed"


def test_placeholder_config_value_is_detected(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/fan.cfg]\n\n"
        "[printer]\n"
        "kinematics: cartesian\n",
        encoding="utf-8",
    )
    (extras_dir / "fan.cfg").write_text(
        "[fan]\n"
        "pin: YOUR_PIN_HERE\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()
    findings = RuleEngine().analyze([], config_snapshot=snapshot)

    assert findings
    assert findings[0].code == "config_placeholder_value"
    assert "YOUR_PIN_HERE" in findings[0].summary
    assert findings[0].source.endswith("fan.cfg:2")
