from klippyai_agent.llm import DiagnosisLLMOutput


def test_diagnosis_output_accepts_structured_list_items() -> None:
    output = DiagnosisLLMOutput.model_validate(
        {
            "summary": {"text": "The extruder section is in printer.cfg."},
            "likely_causes": [{"summary": "The user asked for a config section, not a fault diagnosis."}],
            "recommended_actions": [{"action": "Show the exact [extruder] section from the active config tree."}],
            "follow_up_questions": [{"question": "Do you want related TMC sections too?"}],
        }
    )

    assert output.summary == "The extruder section is in printer.cfg."
    assert output.likely_causes == ["The user asked for a config section, not a fault diagnosis."]
    assert output.recommended_actions == ["Show the exact [extruder] section from the active config tree."]
    assert output.follow_up_questions == ["Do you want related TMC sections too?"]
