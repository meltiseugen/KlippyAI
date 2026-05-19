from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from klippyai_agent.diagnostics import DiagnosticsSnapshot
from klippyai_agent.printerconfig import ConfigRequestTarget, ConfigSnapshot
from klippyai_agent.printerprofile import PrinterProfile
from klippyai_agent.schemas import ConfigProposal, IssueFinding
from klippyai_agent.settings import Settings


class DiagnosisLLMOutput(BaseModel):
    summary: str
    likely_causes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


class ConfigAssistantOutput(BaseModel):
    summary: str
    proposals: list[ConfigProposal] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class DiagnosisPromptPayload:
    user_message: str
    snapshot: DiagnosticsSnapshot
    config_snapshot: ConfigSnapshot
    findings: list[IssueFinding]
    profile: PrinterProfile


@dataclass(slots=True)
class ConfigPromptPayload:
    user_message: str
    snapshot: ConfigSnapshot
    target: ConfigRequestTarget
    profile: PrinterProfile


class DiagnosisProvider(Protocol):
    name: str

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput:
        ...


class ConfigAssistantProvider(Protocol):
    name: str

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput:
        ...


class StubDiagnosisProvider:
    name = "stub"

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput:
        profile_summary = payload.profile.summary_label()
        if payload.findings:
            recommended_actions = [finding.proposed_fix for finding in payload.findings[:3]]
            likely_causes = [finding.summary for finding in payload.findings[:3]]
            summary = "Deterministic diagnostics found printer issues in the supplied artifacts."
            if profile_summary:
                summary += f" Detected printer profile: {profile_summary}."
        else:
            recommended_actions = [
                "Paste relevant klippy.log, moonraker.log, or config excerpts.",
                "Ask a more specific question about the failure mode you are seeing.",
            ]
            likely_causes = [
                "Insufficient context in the current request.",
            ]
            summary = "No deterministic issue matched yet, and no external LLM provider is configured."
            if profile_summary:
                summary += f" Current detected profile: {profile_summary}."

        return DiagnosisLLMOutput(
            summary=summary,
            likely_causes=likely_causes,
            recommended_actions=recommended_actions,
            follow_up_questions=[
                "What changed just before the issue started?",
                "Can you share the exact log lines around the first error?",
            ],
        )


class StubConfigAssistantProvider:
    name = "stub"

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput:
        proposal = self._build_stub_proposal(payload)
        profile_summary = payload.profile.summary_label()
        summary = f"Generated a first-pass {proposal.feature} config proposal based on the current request and collected printer config."
        if profile_summary:
            summary += f" Detected printer profile: {profile_summary}."
        return ConfigAssistantOutput(
            summary=summary,
            proposals=[proposal],
            next_actions=self._build_next_actions(proposal.feature),
            follow_up_questions=self._build_follow_up_questions(proposal.feature),
        )

    def _build_stub_proposal(self, payload: ConfigPromptPayload) -> ConfigProposal:
        feature = payload.target.feature
        warnings = self._common_warnings(payload.snapshot, payload.profile)

        builders = {
            "fan": self._fan_proposal,
            "macro": self._macro_proposal,
            "sensor": self._sensor_proposal,
            "probe": self._probe_proposal,
            "heater": self._heater_proposal,
            "input_shaper": self._input_shaper_proposal,
            "bed_mesh": self._bed_mesh_proposal,
            "filament": self._filament_proposal,
            "canbus": self._canbus_proposal,
            "stepper": self._stepper_proposal,
            "extruder": self._extruder_proposal,
        }
        builder = builders.get(feature, self._generic_proposal)
        return builder(payload, warnings)

    @staticmethod
    def _common_warnings(snapshot: ConfigSnapshot, profile: PrinterProfile) -> list[str]:
        warnings: list[str] = []
        if not snapshot.has_managed_include("klippyai"):
            warnings.append(
                "Your current config does not appear to include a klippyai-managed include path yet. You will need to add one manually."
            )
        if profile.canbus_enabled:
            warnings.append(
                "This printer appears to use CAN-connected hardware. Make sure new pins are assigned under the correct MCU alias."
            )
        return warnings

    def _fan_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.snapshot.has_section_prefix("fan") or payload.snapshot.has_section_prefix("heater_fan"):
            warnings.append("A fan-related section already exists in the current config. Check for overlap before adding another one.")
        return ConfigProposal(
            feature="fan",
            title="Generic PWM fan section",
            target_file="klippyai/fan.cfg",
            config=(
                "[fan]\n"
                "pin: <FAN_PIN>\n"
                "max_power: 1.0\n"
                "kick_start_time: 0.5\n"
                "off_below: 0.10\n"
            ),
            rationale="Baseline controllable fan configuration with the most common tuning options exposed.",
            assumptions=[
                "This is a standard PWM-controllable fan.",
                "You will replace <FAN_PIN> with the actual MCU pin.",
            ],
            warnings=["Replace <FAN_PIN> with the real MCU pin name before using this.", *warnings],
        )

    def _macro_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="macro",
            title="Starter gcode macro",
            target_file="klippyai/macros.cfg",
            config=(
                "[gcode_macro CUSTOM_ACTION]\n"
                "description: Starter macro generated by KlippyAI\n"
                "gcode:\n"
                "  RESPOND MSG=\"Replace this body with your real macro steps\"\n"
            ),
            rationale="A minimal macro stub gives you the correct structure for a new Klipper macro while keeping the logic easy to replace.",
            assumptions=[
                "You want a new macro scaffold rather than edits to an existing macro.",
            ],
            warnings=warnings,
        )

    def _sensor_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="sensor",
            title="Starter temperature sensor section",
            target_file="klippyai/sensor.cfg",
            config=(
                "[temperature_sensor auxiliary_sensor]\n"
                "sensor_type: <SENSOR_TYPE>\n"
                "sensor_pin: <SENSOR_PIN>\n"
                "min_temp: 0\n"
                "max_temp: 100\n"
            ),
            rationale="A generic temperature sensor section is a common starting point when adding enclosure, chamber, or auxiliary sensors.",
            assumptions=[
                "This request is for a passive temperature sensor rather than a probing or filament sensor.",
            ],
            warnings=["Replace <SENSOR_TYPE> and <SENSOR_PIN> with the actual hardware values.", *warnings],
        )

    def _probe_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.probe_type and payload.profile.probe_type not in {"none", "generic"}:
            warnings.append(
                f"The saved printer profile already indicates a {payload.profile.probe_type} probe. Review overlap before adding another probe section."
            )
        return ConfigProposal(
            feature="probe",
            title="Starter probe section",
            target_file="klippyai/probe.cfg",
            config=(
                "[probe]\n"
                "pin: <PROBE_PIN>\n"
                "x_offset: 0\n"
                "y_offset: 0\n"
                "z_offset: 0\n"
                "speed: 5.0\n"
            ),
            rationale="This provides the minimum structure for a generic probe so offsets and pin mapping can be filled in safely.",
            assumptions=[
                "You want a generic probe scaffold, not a BLTouch-specific or Klicky-specific macro suite.",
            ],
            warnings=["Replace <PROBE_PIN> and set real offsets before use.", *warnings],
        )

    def _heater_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="heater",
            title="Starter heater fan section",
            target_file="klippyai/heater.cfg",
            config=(
                "[heater_fan hotend_cooling]\n"
                "pin: <FAN_PIN>\n"
                "heater: extruder\n"
                "heater_temp: 50.0\n"
                "fan_speed: 1.0\n"
            ),
            rationale="A heater_fan section is a common controlled-cooling pattern for hotend fans and similar temperature-driven cooling use cases.",
            assumptions=[
                "This request is closer to a heater-driven fan or cooling behavior than to core heater pin setup.",
            ],
            warnings=["Replace <FAN_PIN> with the correct MCU output pin.", *warnings],
        )

    def _input_shaper_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.accelerometer in {None, "none"}:
            warnings.append(
                "The saved printer profile does not show an accelerometer yet. Verify accelerometer setup before treating this as a tuned input-shaper config."
            )
        return ConfigProposal(
            feature="input_shaper",
            title="Starter input shaper block",
            target_file="klippyai/input_shaper.cfg",
            config=(
                "[input_shaper]\n"
                "shaper_type_x: mzv\n"
                "shaper_freq_x: <X_FREQ>\n"
                "shaper_type_y: mzv\n"
                "shaper_freq_y: <Y_FREQ>\n"
            ),
            rationale="This gives the standard input_shaper structure while leaving the calibrated frequencies as explicit placeholders.",
            assumptions=[
                "You will tune the final frequencies from measured resonance data.",
            ],
            warnings=["Replace <X_FREQ> and <Y_FREQ> with real tuned values.", *warnings],
        )

    def _bed_mesh_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.probe_type in {None, "none"}:
            warnings.append(
                "The saved printer profile does not show a probe yet. Confirm whether this printer will use a probe or a manual mesh workflow."
            )
        return ConfigProposal(
            feature="bed_mesh",
            title="Starter bed mesh section",
            target_file="klippyai/bed_mesh.cfg",
            config=(
                "[bed_mesh]\n"
                "speed: 120\n"
                "horizontal_move_z: 5\n"
                "mesh_min: <MIN_X>,<MIN_Y>\n"
                "mesh_max: <MAX_X>,<MAX_Y>\n"
                "probe_count: 5,5\n"
            ),
            rationale="This is the core Klipper bed mesh structure with placeholders for printable probe bounds.",
            assumptions=[
                "Your printer already has a working probe or probing method.",
            ],
            warnings=["Replace mesh_min and mesh_max with safe reachable probe coordinates.", *warnings],
        )

    def _filament_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        assumptions = [
            "The sensor is a basic switch-style runout detector.",
        ]
        if payload.profile.filament_sensor == "motion":
            warnings.append(
                "The saved printer profile already indicates a motion-style filament sensor. A switch-sensor scaffold may not match your current hardware."
            )
        elif payload.profile.filament_sensor == "switch":
            warnings.append(
                "The saved printer profile already indicates a switch-style filament sensor. Review overlap before adding another runout section."
            )
        elif payload.profile.filament_sensor == "none":
            assumptions.append("The saved printer profile currently shows no filament sensor configured.")
        return ConfigProposal(
            feature="filament",
            title="Starter filament runout sensor section",
            target_file="klippyai/filament.cfg",
            config=(
                "[filament_switch_sensor runout]\n"
                "switch_pin: <SWITCH_PIN>\n"
                "pause_on_runout: True\n"
                "runout_gcode:\n"
                "  PAUSE\n"
            ),
            rationale="This is a safe baseline for a simple filament switch sensor that pauses on runout.",
            assumptions=assumptions,
            warnings=["Replace <SWITCH_PIN> with the actual sensor input pin.", *warnings],
        )

    def _canbus_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if not payload.profile.canbus_enabled:
            warnings.append(
                "The saved printer profile does not show CAN enabled yet. Treat this as an initial CAN bring-up, not an incremental edit to an existing CAN topology."
            )
        return ConfigProposal(
            feature="canbus",
            title="Starter CAN toolhead MCU section",
            target_file="klippyai/canbus.cfg",
            config=(
                "[mcu toolhead]\n"
                "canbus_uuid: <CANBUS_UUID>\n\n"
                "[temperature_sensor toolhead_mcu]\n"
                "sensor_type: temperature_mcu\n"
                "sensor_mcu: toolhead\n"
            ),
            rationale="A CAN toolhead setup usually starts with an MCU declaration and a simple sensor or pin consumer that validates the link.",
            assumptions=[
                "You already know the toolhead board CAN UUID or will fetch it separately.",
            ],
            warnings=["Replace <CANBUS_UUID> with the detected UUID for your toolhead board.", *warnings],
        )

    def _stepper_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="stepper",
            title="Starter TMC driver block",
            target_file="klippyai/stepper.cfg",
            config=(
                "[tmc2209 stepper_x]\n"
                "uart_pin: <UART_PIN>\n"
                "run_current: <RUN_CURRENT>\n"
                "hold_current: <HOLD_CURRENT>\n"
                "sense_resistor: 0.110\n"
            ),
            rationale="A driver-current tuning request usually needs a TMC section scaffold more than a whole kinematics rewrite.",
            assumptions=[
                "This is for a TMC2209-style UART-configured driver on one axis.",
            ],
            warnings=["Replace the UART pin and current values with board-specific values.", *warnings],
        )

    def _extruder_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="extruder",
            title="Starter extruder tuning block",
            target_file="klippyai/extruder.cfg",
            config=(
                "[extruder]\n"
                "step_pin: <STEP_PIN>\n"
                "dir_pin: <DIR_PIN>\n"
                "enable_pin: <ENABLE_PIN>\n"
                "rotation_distance: <ROTATION_DISTANCE>\n"
                "nozzle_diameter: 0.400\n"
                "filament_diameter: 1.750\n"
            ),
            rationale="Extruder setup requests often need a compact scaffold with motion pins and the most critical calibration value, rotation_distance.",
            assumptions=[
                "You want a fresh extruder section scaffold rather than a narrow tuning-only change.",
            ],
            warnings=["Replace all placeholder pins and rotation_distance with your real hardware values.", *warnings],
        )

    def _generic_proposal(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        feature_slug = payload.target.feature if payload.target.feature != "generic" else "custom"
        return ConfigProposal(
            feature=payload.target.feature,
            title="Generic managed include scaffold",
            target_file=f"klippyai/{feature_slug}.cfg",
            config=(
                "# Replace this scaffold with the exact Klipper sections you want.\n"
                f"# Request target detected as: {payload.target.feature}\n"
                "[section_name_here]\n"
                "option_name: <VALUE>\n"
            ),
            rationale="This generic scaffold formats the request as a managed include snippet even when the local stub provider cannot infer a more precise built-in template.",
            assumptions=[
                "The request did not map cleanly to a more specific built-in template.",
            ],
            warnings=["Replace the placeholder section and option names before use.", *warnings],
        )

    @staticmethod
    def _build_next_actions(feature: str) -> list[str]:
        common = [
            "Keep the generated snippet formatted as a managed include snippet under klippyai/*.cfg.",
            "Review the current config for overlapping sections before adding this proposal.",
        ]
        feature_specific = {
            "fan": [
                "Replace the placeholder fan pin with the actual MCU output pin.",
                "Decide whether this should be [fan], [heater_fan], or [controller_fan].",
            ],
            "macro": [
                "Replace the macro body with the exact sequence you want Klipper to run.",
                "Choose a final macro name that matches your workflow.",
            ],
            "sensor": [
                "Replace the sensor type and sensor pin with the real hardware values.",
                "Confirm the expected safe temperature range for this sensor.",
            ],
            "probe": [
                "Replace the probe pin and real probe offsets.",
                "Confirm whether a specialized probe type like BLTouch needs a different section.",
            ],
            "heater": [
                "Confirm whether this should be a heater_fan, temperature_fan, or a different heater-related section.",
                "Replace the placeholder fan pin with the correct output pin.",
            ],
            "input_shaper": [
                "Replace the placeholder shaper frequencies with measured resonance values.",
                "Confirm whether you already have an accelerometer section configured.",
            ],
            "bed_mesh": [
                "Replace mesh bounds with reachable probe coordinates.",
                "Confirm the probe_count and speed fit your printer size and probe type.",
            ],
            "filament": [
                "Replace the switch pin with the actual runout sensor input.",
                "Decide whether you want pause-only behavior or custom runout macros.",
            ],
            "canbus": [
                "Replace the CAN UUID with the real toolhead board UUID.",
                "Confirm the MCU alias matches the rest of your config references.",
            ],
            "stepper": [
                "Replace driver pins and current values with board-specific values.",
                "Confirm the correct driver family before applying the section.",
            ],
            "extruder": [
                "Replace motion pins and calibrate rotation_distance.",
                "Confirm heater and sensor values if this is meant to become a full extruder section.",
            ],
            "generic": [
                "Rewrite the generic scaffold into the exact Klipper section you need.",
                "Ask a more specific follow-up for tighter config generation.",
            ],
        }
        return [*feature_specific.get(feature, feature_specific["generic"]), *common]

    @staticmethod
    def _build_follow_up_questions(feature: str) -> list[str]:
        questions = {
            "fan": [
                "Is this a part-cooling fan, hotend fan, controller fan, or chamber fan?",
                "What MCU pin is the fan connected to?",
            ],
            "macro": [
                "What should the macro do step by step?",
                "Do you want it to call existing Klipper macros or stand alone?",
            ],
            "sensor": [
                "What exact sensor hardware are you using?",
                "What pin is the sensor connected to?",
            ],
            "probe": [
                "What probe hardware are you using?",
                "Do you already know the probe offsets or should those remain placeholders?",
            ],
            "heater": [
                "Is this for a hotend cooling fan, chamber control, or another heater-linked behavior?",
                "What output pin should control it?",
            ],
            "input_shaper": [
                "Do you already have measured resonance frequencies?",
                "Is your accelerometer already configured in Klipper?",
            ],
            "bed_mesh": [
                "What are the safe probe bounds on your bed?",
                "What probe hardware are you using for bed mesh generation?",
            ],
            "filament": [
                "Is the sensor a simple switch or a motion sensor?",
                "Do you want pause behavior only or custom runout actions too?",
            ],
            "canbus": [
                "What CAN toolhead board are you using?",
                "Do you already know the CAN UUID and desired MCU alias?",
            ],
            "stepper": [
                "Which axis or motor are you tuning?",
                "What driver family are you using?",
            ],
            "extruder": [
                "Is this a full extruder section or just a tuning adjustment?",
                "Do you already know the calibrated rotation_distance?",
            ],
            "generic": [
                "Which exact printer feature do you want to configure?",
                "Do you want the proposal formatted as a managed include snippet under klippyai/*.cfg?",
            ],
        }
        return questions.get(feature, questions["generic"])


class OpenAIDiagnosisProvider:
    name = "openai"

    _PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are an expert Klipper and Moonraker diagnostics assistant. "
                    "Use supplied evidence first, do not invent printer state, keep the answer grounded, "
                    "and propose safe next steps before any invasive change. "
                    "Use the detected printer profile to avoid assuming the wrong firmware flavor, probe, MCU, or addon stack."
                ),
            ),
            (
                "human",
                (
                    "User request:\n{user_message}\n\n"
                    "Detected printer profile:\n{profile_block}\n\n"
                    "Collected context:\n{context_block}\n\n"
                    "Current config context:\n{config_block}\n\n"
                    "Deterministic findings:\n{findings_block}\n\n"
                    "Return a concise structured diagnosis."
                ),
            ),
        ]
    )

    def __init__(self, model: str, api_key: str | None) -> None:
        kwargs: dict[str, object] = {
            "model": model,
            "temperature": 0,
        }
        if api_key:
            kwargs["api_key"] = api_key
        self._model = ChatOpenAI(**kwargs).with_structured_output(DiagnosisLLMOutput)

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput:
        findings_block = "\n".join(
            f"- [{finding.severity}] {finding.summary} | evidence: {finding.evidence} | fix: {finding.proposed_fix}"
            for finding in payload.findings
        )
        if not findings_block:
            findings_block = "No deterministic findings."

        chain = self._PROMPT | self._model
        return await chain.ainvoke(
            {
                "user_message": payload.user_message,
                "profile_block": payload.profile.to_prompt_block(),
                "context_block": payload.snapshot.to_prompt_block(),
                "config_block": payload.config_snapshot.to_prompt_block(max_documents=6),
                "findings_block": findings_block,
            }
        )


class OpenAIConfigAssistantProvider:
    name = "openai"

    _PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are an expert Klipper and Kalico configuration assistant. "
                    "Generate safe, reviewable config snippets only. Prefer managed include snippets under klippyai/*.cfg. "
                    "Do not imply that you can write files or apply changes directly. "
                    "Do not invent existing pins or hardware details. If details are missing, use placeholders and list the assumptions clearly. "
                    "Use the detected printer profile to tailor suggestions to the printer's firmware flavor, MCU layout, and installed addons."
                ),
            ),
            (
                "human",
                (
                    "User request:\n{user_message}\n\n"
                    "Detected printer profile:\n{profile_block}\n\n"
                    "Detected target:\n{target_feature}\n"
                    "Detection rationale:\n{target_rationale}\n\n"
                    "Current config context:\n{config_block}\n\n"
                    "Return a concise structured config proposal."
                ),
            ),
        ]
    )

    def __init__(self, model: str, api_key: str | None) -> None:
        kwargs: dict[str, object] = {
            "model": model,
            "temperature": 0,
        }
        if api_key:
            kwargs["api_key"] = api_key
        self._model = ChatOpenAI(**kwargs).with_structured_output(ConfigAssistantOutput)

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput:
        chain = self._PROMPT | self._model
        return await chain.ainvoke(
            {
                "user_message": payload.user_message,
                "profile_block": payload.profile.to_prompt_block(),
                "target_feature": payload.target.feature,
                "target_rationale": payload.target.rationale,
                "config_block": payload.snapshot.to_prompt_block(),
            }
        )


def build_diagnosis_provider(settings: Settings) -> DiagnosisProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIDiagnosisProvider(
            model=settings.openai_model,
            api_key=api_key,
        )
    return StubDiagnosisProvider()


def build_config_provider(settings: Settings) -> ConfigAssistantProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIConfigAssistantProvider(
            model=settings.openai_model,
            api_key=api_key,
        )
    return StubConfigAssistantProvider()
