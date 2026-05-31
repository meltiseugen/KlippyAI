from __future__ import annotations

from pathlib import Path

from klippyai_agent.printerconfig import (
    build_config_lookup_response,
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
    assert snapshot.root_file == "printer.cfg"
    assert {document.path for document in snapshot.documents} == {"printer.cfg", "extras/fan.cfg"}
    assert str(tmp_path) not in snapshot.to_prompt_block()


def test_config_collector_auto_detects_nonstandard_root_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    machine_dir = config_dir / "machines" / "voron"
    extras_dir = config_dir / "extras"
    machine_dir.mkdir(parents=True)
    extras_dir.mkdir(parents=True)

    (machine_dir / "printer-main.cfg").write_text(
        "[include ../../extras/toolhead.cfg]\n\n"
        "[printer]\n"
        "kinematics: corexy\n",
        encoding="utf-8",
    )
    (extras_dir / "toolhead.cfg").write_text(
        "[fan]\n"
        "pin: PA1\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()

    assert snapshot.root_file is not None
    assert snapshot.root_file.endswith("printer-main.cfg")
    assert len(snapshot.documents) == 2
    assert any("Auto-detected root config file" in note for note in snapshot.notes)


def test_config_collector_respects_ignore_globs(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    backup_dir = extras_dir / "archive"
    extras_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/**/*.cfg]\n\n"
        "[printer]\n"
        "kinematics: cartesian\n",
        encoding="utf-8",
    )
    (extras_dir / "fan.cfg").write_text(
        "[fan]\n"
        "pin: PA1\n",
        encoding="utf-8",
    )
    (backup_dir / "old.cfg").write_text(
        "[fan_generic archived]\n"
        "pin: PB1\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(
        tmp_path / "printer_data",
        ignore_globs="extras/archive/**",
    ).collect()

    collected_paths = {Path(document.path).as_posix() for document in snapshot.documents}
    assert any(path.endswith("printer.cfg") for path in collected_paths)
    assert any(path.endswith("fan.cfg") for path in collected_paths)
    assert not any(path.endswith("old.cfg") for path in collected_paths)
    assert any("Ignored config file due to config_context.ignore_globs" in note for note in snapshot.notes)


def test_config_collector_detects_active_placeholder_values(tmp_path: Path) -> None:
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

    assert len(snapshot.placeholders) == 1
    placeholder = snapshot.placeholders[0]
    assert placeholder.path.endswith("fan.cfg")
    assert placeholder.line_number == 2
    assert placeholder.section == "fan"
    assert placeholder.option == "pin"
    assert placeholder.value == "YOUR_PIN_HERE"


def test_config_collector_tracks_section_locations_in_active_include_tree(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/toolhead.cfg]\n\n"
        "[printer]\n"
        "kinematics: corexy\n",
        encoding="utf-8",
    )
    (extras_dir / "toolhead.cfg").write_text(
        "[extruder]\n"
        "step_pin: PA1\n\n"
        "[fan]\n"
        "pin: PB1\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()

    matches = [location for location in snapshot.section_locations if location.section == "extruder"]
    assert len(matches) == 1
    assert matches[0].path.endswith("toolhead.cfg")
    assert matches[0].line_number == 1


def test_config_request_detects_section_content_followup() -> None:
    target = infer_config_request_target("can you give me the extruder section here?")

    assert target.feature == "extruder"
    assert target.intent == "locate"


def test_config_collector_includes_all_files_from_active_include_tree(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    include_lines = []
    for index in range(1, 15):
        file_name = f"part_{index}.cfg"
        include_lines.append(f"[include extras/{file_name}]")
        (extras_dir / file_name).write_text(
            f"[fan_generic part_{index}]\n"
            f"pin: P{index}\n",
            encoding="utf-8",
        )

    (config_dir / "printer.cfg").write_text(
        "\n".join(include_lines)
        + "\n\n[printer]\nkinematics: cartesian\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()

    assert len(snapshot.documents) == 15
    prompt_block = snapshot.to_prompt_block()
    assert "part_14.cfg" in prompt_block


def test_config_collector_keeps_full_file_text_by_default(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)
    long_line = "A" * 15_000

    (config_dir / "printer.cfg").write_text(
        "[include extras/long.cfg]\n\n"
        "[printer]\n"
        "kinematics: cartesian\n",
        encoding="utf-8",
    )
    (extras_dir / "long.cfg").write_text(
        "[gcode_macro LONG_TEST]\n"
        f"description: {long_line}\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()

    long_document = next(document for document in snapshot.documents if document.path.endswith("long.cfg"))
    assert "[truncated]" not in long_document.content
    assert long_line in long_document.content


def test_config_request_detection_finds_fan_generation_intent() -> None:
    message = "Generate me a config for a fan on my toolhead board"

    assert looks_like_config_request(message) is True
    target = infer_config_request_target(message)
    assert target.feature == "fan"
    assert target.intent == "generate"


def test_config_request_detection_handles_macro_and_extruder_requests() -> None:
    macro_message = "Improve my start print macro config"
    extruder_message = "Create an extruder config scaffold for this printer"

    assert looks_like_config_request(macro_message) is True
    assert infer_config_request_target(macro_message).feature == "macro"

    assert looks_like_config_request(extruder_message) is True
    assert infer_config_request_target(extruder_message).feature == "extruder"


def test_config_request_detection_handles_lookup_queries() -> None:
    message = "Where do I have the extruder defined?"
    direct_section_message = "Which file has [fan]?"

    assert looks_like_config_request(message) is True
    target = infer_config_request_target(message)
    assert target.feature == "extruder"
    assert target.intent == "locate"
    assert target.section_name is None

    assert looks_like_config_request(direct_section_message) is True
    direct_target = infer_config_request_target(direct_section_message)
    assert direct_target.intent == "locate"
    assert direct_target.section_name == "fan"


def test_config_request_detection_treats_bare_macro_name_as_exact_lookup() -> None:
    messages = [
        "Where is my sfs_enable macro defined?",
        "where is SFS_ENABLE macro defined?",
    ]

    for message in messages:
        assert looks_like_config_request(message) is True
        target = infer_config_request_target(message)

        assert target.feature == "macro"
        assert target.intent == "locate"
        assert target.section_name == "gcode_macro SFS_ENABLE"


def test_config_request_detection_treats_macro_questions_as_explain_intent() -> None:
    message = "What does SFS_ENABLE do?"

    assert looks_like_config_request(message) is True
    target = infer_config_request_target(message)

    assert target.feature == "macro"
    assert target.intent == "explain"
    assert target.section_name == "gcode_macro SFS_ENABLE"


def test_build_config_lookup_response_returns_exact_section_locations(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/toolhead.cfg]\n\n"
        "[printer]\n"
        "kinematics: corexy\n",
        encoding="utf-8",
    )
    (extras_dir / "toolhead.cfg").write_text(
        "[extruder]\n"
        "step_pin: PA1\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()
    target = infer_config_request_target("Where do I have the extruder defined?")
    response_text, next_actions = build_config_lookup_response(snapshot, target)

    assert "Matches:" in response_text
    assert "[extruder]" in response_text
    assert "toolhead.cfg:1" in response_text
    assert not next_actions


def test_build_config_lookup_response_returns_exact_macro_definition_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    klippy_dir = config_dir / "Klippy"
    klippy_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include Klippy/filament.cfg]\n"
        "[include macros.cfg]\n\n"
        "[printer]\n"
        "kinematics: cartesian\n",
        encoding="utf-8",
    )
    (klippy_dir / "filament.cfg").write_text(
        "[gcode_macro SFS_ENABLE]\n"
        "description: Enable smart filament sensor checks\n"
        "gcode:\n"
        "  SET_FILAMENT_SENSOR SENSOR=switch_sensor ENABLE=1\n",
        encoding="utf-8",
    )
    (config_dir / "macros.cfg").write_text(
        "[gcode_macro PRINT_START]\n"
        "gcode:\n"
        "  G28\n"
        "  SFS_ENABLE\n",
        encoding="utf-8",
    )

    snapshot = ConfigCollector(tmp_path / "printer_data").collect()
    target = infer_config_request_target("Where is my sfs_enable macro defined?")
    response_text, next_actions = build_config_lookup_response(snapshot, target)

    assert response_text.startswith("SFS_ENABLE is defined in ")
    assert "Klippy" in response_text
    assert "filament.cfg:1" in response_text
    assert "[gcode_macro SFS_ENABLE]" in response_text
    assert "Used by:" in response_text
    assert "[gcode_macro PRINT_START]" in response_text
    assert "macros.cfg:4" in response_text
    assert "Description: Enable smart filament sensor checks" in response_text
    assert "enables filament sensor `switch_sensor`" in response_text
    assert "Most likely:" not in response_text
    assert "Fix:" not in response_text
    assert "Matches:" not in response_text
    assert not next_actions
