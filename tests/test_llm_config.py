from __future__ import annotations

import pytest

from klippyai_agent.llm import ConfigPromptPayload, StubConfigAssistantProvider
from klippyai_agent.printerconfig import ConfigRequestTarget, ConfigSnapshot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("feature", "expected_target"),
    [
        ("fan", "klippyai/fan.cfg"),
        ("macro", "klippyai/macros.cfg"),
        ("sensor", "klippyai/sensor.cfg"),
        ("probe", "klippyai/probe.cfg"),
        ("heater", "klippyai/heater.cfg"),
        ("input_shaper", "klippyai/input_shaper.cfg"),
        ("bed_mesh", "klippyai/bed_mesh.cfg"),
        ("filament", "klippyai/filament.cfg"),
        ("canbus", "klippyai/canbus.cfg"),
        ("stepper", "klippyai/stepper.cfg"),
        ("extruder", "klippyai/extruder.cfg"),
        ("generic", "klippyai/custom.cfg"),
    ],
)
async def test_stub_config_provider_returns_a_proposal_for_each_feature(
    feature: str,
    expected_target: str,
) -> None:
    provider = StubConfigAssistantProvider()
    payload = ConfigPromptPayload(
        user_message=f"Generate me a {feature} config",
        snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        target=ConfigRequestTarget(feature=feature, rationale="test"),
    )

    result = await provider.propose(payload)

    assert result.proposals
    assert result.proposals[0].target_file == expected_target
