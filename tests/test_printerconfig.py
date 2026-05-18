from __future__ import annotations

from pathlib import Path

from klippyai_agent.printerconfig import (
    ConfigCollector,
    infer_config_request_target,
    looks_like_config_request,
)


def test_config_collector_reads_printer_cfg_and_includes(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/fan.cfg]\n"
        "[include klippyai/*.cfg]\n\n"
        "[printer]\n"
        "kinematics: cartesian\n",
        encoding="utf-8",
    )
    (extras_dir / "fan.cfg").write_text(
        "[fan]\n"
        "pin: PA1\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()

    assert snapshot.root_file is not None
    assert len(snapshot.documents) == 2
    assert snapshot.has_section_prefix("fan") is True
    assert snapshot.has_managed_include("klippyai") is True


def test_config_request_detection_finds_fan_generation_intent() -> None:
    message = "Generate me a config for a fan on my toolhead board"

    assert looks_like_config_request(message) is True
    target = infer_config_request_target(message)
    assert target.feature == "fan"


def test_config_request_detection_handles_macro_and_extruder_requests() -> None:
    macro_message = "Improve my start print macro config"
    extruder_message = "Create an extruder config scaffold for this printer"

    assert looks_like_config_request(macro_message) is True
    assert infer_config_request_target(macro_message).feature == "macro"

    assert looks_like_config_request(extruder_message) is True
    assert infer_config_request_target(extruder_message).feature == "extruder"
