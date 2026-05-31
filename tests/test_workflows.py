from pathlib import Path
from types import SimpleNamespace

import pytest

from klippyai_agent.hostlogs import HostLogCollector
from klippyai_agent.printerconfig import ConfigCollector
from klippyai_agent.printerconfig import ConfigSnapshot, infer_config_request_target
from klippyai_agent.workflows import compose_config_response
from klippyai_agent.workflows import compose_response
from klippyai_agent.workflows import collect_config_context
from klippyai_agent.workflows import resolve_config_lookup


def test_compose_response_prefers_findings_and_keeps_output_compact() -> None:
    result = compose_response(
        {
            "findings": [
                {
                    "severity": "high",
                    "summary": "Placeholder value YOUR_PIN_HERE is still active in section [fan] for option 'pin'.",
                    "source": "/home/pi/printer_data/config/extras/fan.cfg:2",
                    "proposed_fix": "Replace YOUR_PIN_HERE with the real MCU pin.",
                }
            ],
            "llm_output": {
                "summary": "Klipper is shut down because an active config file still contains a placeholder pin value.",
                "likely_causes": ["Repeated cause that should be omitted when findings exist."],
                "recommended_actions": [
                    "Replace YOUR_PIN_HERE with the real MCU pin.",
                    "Restart Klipper.",
                    "Confirm the fan section references the correct MCU alias.",
                    "This fourth action should be trimmed.",
                ],
                "follow_up_questions": [
                    "This follow-up should not be shown when findings exist.",
                ],
            },
        }
    )

    assert "Location: /home/pi/printer_data/config/extras/fan.cfg:2" in result["response_text"]
    assert "Fix:" in result["response_text"]
    assert "Findings:" not in result["response_text"]
    assert "Likely causes:" not in result["response_text"]
    assert "Need:" not in result["response_text"]
    assert "This fourth action should be trimmed." not in result["response_text"]


def test_compose_config_response_keeps_text_short_and_avoids_code_duplication() -> None:
    result = compose_config_response(
        {
            "config_output": {
                "summary": "Generated a first-pass fan config proposal.",
                "proposals": [
                    {
                        "feature": "fan",
                        "title": "Generic PWM fan section",
                        "target_file": "klippyai/fan.cfg",
                        "config": "[fan]\npin: <FAN_PIN>\n",
                        "rationale": "test",
                        "assumptions": ["A"],
                        "warnings": ["B"],
                    }
                ],
                "next_actions": [
                    "Replace the placeholder fan pin with the actual MCU output pin.",
                    "Decide whether this should be [fan], [heater_fan], or [controller_fan].",
                    "This third line should be trimmed.",
                ],
                "follow_up_questions": [
                    "This question should not be shown because next actions exist.",
                ],
            }
        }
    )

    assert "Proposal:" in result["response_text"]
    assert "Generic PWM fan section -> klippyai/fan.cfg" in result["response_text"]
    assert "```ini" not in result["response_text"]
    assert "Assumptions:" not in result["response_text"]
    assert "Warnings:" not in result["response_text"]
    assert "This third line should be trimmed." not in result["response_text"]
    assert "This question should not be shown" not in result["response_text"]


def test_resolve_config_lookup_returns_exact_match_without_llm() -> None:
    target = infer_config_request_target("Which file has [fan]?")
    snapshot = ConfigSnapshot.from_state(
        {
            "root_file": "/home/pi/printer_data/config/printer.cfg",
            "documents": [],
            "notes": [],
            "section_locations": [
                {
                    "path": "/home/pi/printer_data/config/extras/cooling.cfg",
                    "line_number": 7,
                    "section": "fan",
                },
                {
                    "path": "/home/pi/printer_data/config/extras/cooling.cfg",
                    "line_number": 12,
                    "section": "fan_generic nevermore",
                },
            ],
        }
    )

    result = resolve_config_lookup(
        {
            "feature_target": {
                "feature": target.feature,
                "rationale": target.rationale,
                "intent": target.intent,
                "section_name": target.section_name,
            },
            "config_snapshot": snapshot.to_state(),
        }
    )

    assert "Matches:" in result["response_text"]
    assert "[fan] at /home/pi/printer_data/config/extras/cooling.cfg:7" in result["response_text"]
    assert "fan_generic nevermore" not in result["response_text"]


def test_resolve_config_lookup_can_return_section_body_without_llm() -> None:
    target = infer_config_request_target("Can you give me the extruder section here?")
    snapshot = ConfigSnapshot.from_state(
        {
            "root_file": "/home/pi/printer_data/config/printer.cfg",
            "documents": [
                {
                    "path": "/home/pi/printer_data/config/printer.cfg",
                    "sections": ["extruder", "heater_bed"],
                    "content": (
                        "[extruder]\n"
                        "step_pin: PA1\n"
                        "rotation_distance: 7.5\n\n"
                        "[heater_bed]\n"
                        "heater_pin: PB1\n"
                    ),
                }
            ],
            "notes": [],
            "section_locations": [
                {
                    "path": "/home/pi/printer_data/config/printer.cfg",
                    "line_number": 1,
                    "section": "extruder",
                },
                {
                    "path": "/home/pi/printer_data/config/printer.cfg",
                    "line_number": 5,
                    "section": "heater_bed",
                },
            ],
        }
    )

    result = resolve_config_lookup(
        {
            "user_message": "Can you give me the extruder section here?",
            "feature_target": {
                "feature": target.feature,
                "rationale": target.rationale,
                "intent": target.intent,
                "section_name": target.section_name,
            },
            "config_snapshot": snapshot.to_state(),
        }
    )

    assert target.intent == "locate"
    assert "```ini" in result["response_text"]
    assert "[extruder]" in result["response_text"]
    assert "rotation_distance: 7.5" in result["response_text"]
    assert "[heater_bed]" not in result["response_text"]


@pytest.mark.asyncio
async def test_collect_config_context_skips_host_logs_for_config_lookup_by_default(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    logs_dir = tmp_path / "printer_data" / "logs"
    config_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    (config_dir / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n", encoding="utf-8")
    (logs_dir / "klippy.log").write_text("line 1\nline 2\n", encoding="utf-8")

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            config_collector=ConfigCollector(tmp_path / "printer_data"),
            host_logs=HostLogCollector(tmp_path / "printer_data", default_tail_lines=100),
        )
    )

    result = await collect_config_context({}, runtime)

    assert result["config_snapshot"]["documents"]
    assert result["runtime_snapshot"]["artifacts"] == []


@pytest.mark.asyncio
async def test_collect_config_context_merges_request_artifacts_with_host_logs_when_needed(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    logs_dir = tmp_path / "printer_data" / "logs"
    config_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    (config_dir / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n", encoding="utf-8")
    (logs_dir / "klippy.log").write_text("line 1\nline 2\n", encoding="utf-8")

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            config_collector=ConfigCollector(tmp_path / "printer_data"),
            host_logs=HostLogCollector(tmp_path / "printer_data", default_tail_lines=100),
        )
    )

    result = await collect_config_context(
        {
            "chat_intent": {
                "intent": "diagnose_issue",
                "needs_logs": True,
            },
            "artifacts": [
                {
                    "kind": "config_snippet",
                    "label": "question-context",
                    "content": "[fan]\npin: PA1\n",
                }
            ]
        },
        runtime,
    )

    labels = [artifact["label"] for artifact in result["runtime_snapshot"]["artifacts"]]
    assert labels[0] == "question-context"
    assert "klippy.log" in labels
