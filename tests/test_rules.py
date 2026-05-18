from klippyai_agent.diagnostics import RuleEngine
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
