from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, TypedDict

from klippyai_agent.diagnostics import DiagnosticsCollector, DiagnosticsSnapshot, RuleEngine
from klippyai_agent.hostlogs import HostLogCollector
from klippyai_agent.intent import IntentRouterProvider
from klippyai_agent.llm import (
    ConfigAssistantProvider,
    ConfigPromptPayload,
    DiagnosisPromptPayload,
    DiagnosisProvider,
)
from klippyai_agent.printerconfig import (
    build_config_lookup_response,
    ConfigCollector,
    ConfigRequestTarget,
    ConfigSnapshot,
    infer_config_request_target,
    looks_like_config_content_request,
)
from klippyai_agent.printerprofile import PrinterProfile
from klippyai_agent.schemas import ArtifactInput, ConfigProposal, IssueFinding


@dataclass(slots=True)
class WorkflowContext:
    collector: DiagnosticsCollector
    rules: RuleEngine
    llm: DiagnosisProvider
    intent_router: IntentRouterProvider | None
    config_collector: ConfigCollector
    config_llm: ConfigAssistantProvider
    host_logs: HostLogCollector | None
    profile: PrinterProfile


@dataclass(slots=True)
class WorkflowRuntime:
    context: WorkflowContext


class DiagnosisState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_message: str
    conversation_context: str
    artifacts: list[dict[str, Any]]
    snapshot: dict[str, Any]
    config_snapshot: dict[str, Any]
    findings: list[dict[str, Any]]
    llm_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    moonraker_reachable: bool
    patch_proposals: list[dict[str, Any]]
    chat_intent: dict[str, Any]


class ApplyChangeState(TypedDict, total=False):
    target_file: str
    diff: str
    rationale: str
    approval: str
    status: str


class ConfigState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_message: str
    conversation_context: str
    artifacts: list[dict[str, Any]]
    feature_target: dict[str, Any]
    config_snapshot: dict[str, Any]
    runtime_snapshot: dict[str, Any]
    config_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    config_proposals: list[dict[str, Any]]
    chat_intent: dict[str, Any]


async def collect_context(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    input_artifacts = [ArtifactInput.model_validate(item) for item in state.get("artifacts", [])]
    chat_intent = state.get("chat_intent", {})
    include_runtime_context = bool(chat_intent.get("needs_logs", True))
    snapshot = await runtime.context.collector.collect(
        input_artifacts,
        include_host_logs=include_runtime_context,
        include_host_system=include_runtime_context,
    )
    config_snapshot = runtime.context.config_collector.collect()
    return {
        "artifacts": [artifact.model_dump() for artifact in input_artifacts],
        "snapshot": {
            "moonraker_reachable": snapshot.moonraker_reachable,
            "moonraker_info": snapshot.moonraker_info,
            "notes": snapshot.notes,
            "artifacts": [artifact.model_dump() for artifact in snapshot.artifacts],
        },
        "config_snapshot": config_snapshot.to_state(),
        "moonraker_reachable": snapshot.moonraker_reachable,
    }


async def run_rules(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    snapshot_data = state.get("snapshot", {})
    artifact_items = snapshot_data.get("artifacts", state.get("artifacts", []))
    artifacts = [ArtifactInput.model_validate(item) for item in artifact_items]
    config_snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    findings = runtime.context.rules.analyze(artifacts, config_snapshot=config_snapshot)
    return {
        "findings": [finding.model_dump() for finding in findings],
        "patch_proposals": [],
    }


async def call_llm(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    snapshot_data = state.get("snapshot", {})
    artifact_items = snapshot_data.get("artifacts", state.get("artifacts", []))
    artifacts = [ArtifactInput.model_validate(item) for item in artifact_items]
    findings = [IssueFinding.model_validate(item) for item in state.get("findings", [])]
    snapshot = DiagnosticsSnapshot(
        moonraker_reachable=bool(snapshot_data.get("moonraker_reachable", False)),
        moonraker_info=snapshot_data.get("moonraker_info"),
        artifacts=artifacts,
        notes=list(snapshot_data.get("notes", [])),
    )
    config_snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    payload = DiagnosisPromptPayload(
        user_message=state["user_message"],
        conversation_context=state.get("conversation_context", ""),
        snapshot=snapshot,
        config_snapshot=config_snapshot,
        findings=findings,
        profile=runtime.context.profile,
    )
    llm_output = await runtime.context.llm.analyze(payload)
    return {"llm_output": llm_output.model_dump()}


def compose_response(state: DiagnosisState) -> DiagnosisState:
    findings = state.get("findings", [])
    llm_output = state.get("llm_output", {})
    summary = str(llm_output.get("summary", "No summary available.")).strip()
    likely_causes = llm_output.get("likely_causes", [])
    recommended_actions = llm_output.get("recommended_actions", [])
    follow_up_questions = llm_output.get("follow_up_questions", [])

    lines = [summary]

    if findings:
        primary_finding = findings[0]
        source = str(primary_finding.get("source", "")).strip()
        if source and source not in summary:
            lines.append(f"Location: {source}")
    elif likely_causes:
        primary_cause = str(likely_causes[0]).strip()
        if primary_cause and primary_cause not in summary:
            lines.append(f"Most likely: {primary_cause}")

    concise_actions = _dedupe_items(recommended_actions, limit=2)
    if concise_actions:
        lines.append("")
        lines.append("Fix:")
        for item in concise_actions:
            lines.append(f"- {item}")
    elif not findings and follow_up_questions:
        lines.append("")
        lines.append("Need:")
        for item in follow_up_questions[:1]:
            lines.append(f"- {item}")

    fallback_actions = [finding["proposed_fix"] for finding in findings[:2]]
    next_actions = concise_actions or _dedupe_items(fallback_actions, limit=2)
    return {
        "response_text": "\n".join(lines).strip(),
        "next_actions": next_actions,
    }


def _config_target_from_chat_intent(state: ConfigState) -> ConfigRequestTarget | None:
    chat_intent = state.get("chat_intent", {})
    intent_name = str(chat_intent.get("intent", "")).strip()
    if intent_name not in {"config_lookup", "config_explain", "edit_existing_config"}:
        return None

    target_section = str(chat_intent.get("target_section") or "").strip().strip("[]")
    if target_section:
        detected = infer_config_request_target(f"Which file has [{target_section}]?")
    else:
        target_text = str(chat_intent.get("target") or "").strip()
        if not target_text:
            intent_map = {
                "config_lookup": "locate",
                "config_explain": "explain",
                "edit_existing_config": "edit",
            }
            return ConfigRequestTarget(
                feature="generic",
                rationale=chat_intent.get("rationale") or "Follow-up config request with no explicit target.",
                intent=intent_map.get(intent_name, "locate"),
                section_name=None,
            )
        prompt = (
            f"Where is {target_text} macro defined?"
            if _looks_like_macro_target(target_text)
            else f"Where is {target_text} defined?"
        )
        detected = infer_config_request_target(prompt)

    if intent_name == "config_explain":
        return ConfigRequestTarget(
            feature=detected.feature,
            rationale=chat_intent.get("rationale") or detected.rationale,
            intent="explain",
            section_name=detected.section_name,
        )

    if intent_name == "edit_existing_config":
        return ConfigRequestTarget(
            feature=detected.feature,
            rationale=chat_intent.get("rationale") or detected.rationale,
            intent="edit",
            section_name=detected.section_name,
        )

    return detected


def _looks_like_macro_target(target_text: str) -> bool:
    normalized = target_text.strip().strip("[]")
    lowered = normalized.lower()
    return lowered.startswith("gcode_macro ") or "_" in normalized or normalized.isupper()


def detect_config_target(state: ConfigState) -> ConfigState:
    target = _config_target_from_chat_intent(state) or infer_config_request_target(state["user_message"])
    return {
        "feature_target": {
            "feature": target.feature,
            "rationale": target.rationale,
            "intent": target.intent,
            "section_name": target.section_name,
        }
    }


async def collect_config_context(
    state: ConfigState,
    runtime: WorkflowRuntime,
) -> ConfigState:
    target_data = state.get("feature_target", {})
    include_unincluded_configs = target_data.get("intent") in {"locate", "explain", "edit"}
    snapshot = runtime.context.config_collector.collect_with_options(
        include_unincluded_configs=include_unincluded_configs
    )
    input_artifacts = [ArtifactInput.model_validate(item) for item in state.get("artifacts", [])]
    chat_intent = state.get("chat_intent", {})
    include_runtime_context = bool(state.get("include_runtime_context", False) or chat_intent.get("needs_logs", False))
    runtime_snapshot = DiagnosticsSnapshot(
        moonraker_reachable=False,
        moonraker_info=None,
        artifacts=list(input_artifacts),
        notes=[],
    )
    if include_runtime_context and runtime.context.host_logs is not None:
        host_artifacts, host_notes = runtime.context.host_logs.collect()
        runtime_snapshot = DiagnosticsSnapshot(
            moonraker_reachable=False,
            moonraker_info=None,
            artifacts=[*input_artifacts, *host_artifacts],
            notes=host_notes,
        )
    return {
        "artifacts": [artifact.model_dump() for artifact in input_artifacts],
        "config_snapshot": snapshot.to_state(),
        "runtime_snapshot": {
            "moonraker_reachable": runtime_snapshot.moonraker_reachable,
            "moonraker_info": runtime_snapshot.moonraker_info,
            "notes": runtime_snapshot.notes,
            "artifacts": [artifact.model_dump() for artifact in runtime_snapshot.artifacts],
        },
    }


def resolve_config_lookup(state: ConfigState) -> ConfigState:
    target_data = state.get("feature_target", {})
    if target_data.get("intent") not in {"locate", "explain"}:
        return {}

    snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    target = ConfigRequestTarget(
        feature=target_data.get("feature", "generic"),
        rationale=target_data.get("rationale", "Matched config lookup request."),
        intent=target_data.get("intent", "locate"),
        section_name=target_data.get("section_name"),
    )
    response_text, next_actions = build_config_lookup_response(
        snapshot,
        target,
        include_content=looks_like_config_content_request(state.get("user_message", "")),
    )
    return {
        "response_text": response_text,
        "next_actions": next_actions,
        "config_proposals": [],
    }


async def call_config_llm(
    state: ConfigState,
    runtime: WorkflowRuntime,
) -> ConfigState:
    target_data = state.get("feature_target", {})
    snapshot_data = state.get("config_snapshot", {})
    detected = infer_config_request_target(state["user_message"])
    target = ConfigRequestTarget(
        feature=target_data.get("feature", detected.feature),
        rationale=target_data.get("rationale", detected.rationale),
        intent=target_data.get("intent", detected.intent),
        section_name=target_data.get("section_name", detected.section_name),
    )

    snapshot = ConfigSnapshot.from_state(snapshot_data)
    runtime_snapshot_data = state.get("runtime_snapshot", {})
    runtime_artifacts = [ArtifactInput.model_validate(item) for item in runtime_snapshot_data.get("artifacts", [])]
    runtime_snapshot = DiagnosticsSnapshot(
        moonraker_reachable=bool(runtime_snapshot_data.get("moonraker_reachable", False)),
        moonraker_info=runtime_snapshot_data.get("moonraker_info"),
        artifacts=runtime_artifacts,
        notes=list(runtime_snapshot_data.get("notes", [])),
    )
    payload = ConfigPromptPayload(
        user_message=state["user_message"],
        conversation_context=state.get("conversation_context", ""),
        snapshot=snapshot,
        target=target,
        runtime_snapshot=runtime_snapshot,
        profile=runtime.context.profile,
    )
    config_output = await runtime.context.config_llm.propose(payload)
    return {"config_output": config_output.model_dump()}


def compose_config_response(state: ConfigState) -> ConfigState:
    output = state.get("config_output", {})
    summary = output.get("summary", "No config proposal was generated.")
    proposals = [ConfigProposal.model_validate(item) for item in output.get("proposals", [])]
    next_actions = _dedupe_items(output.get("next_actions", []), limit=2)
    follow_up_questions = list(output.get("follow_up_questions", []))

    lines = [summary]

    if proposals:
        lines.append("")
        lines.append("Proposal:")
        for proposal in proposals[:2]:
            lines.append(f"- {proposal.title} -> {proposal.target_file}")

    if next_actions:
        lines.append("")
        lines.append("Next:")
        for item in next_actions:
            lines.append(f"- {item}")

    if follow_up_questions and not next_actions:
        lines.append("")
        lines.append("Need:")
        for item in follow_up_questions[:1]:
            lines.append(f"- {item}")

    return {
        "response_text": "\n".join(lines).strip(),
        "next_actions": next_actions,
        "config_proposals": [proposal.model_dump() for proposal in proposals],
    }


def _dedupe_items(items: list[str] | tuple[str, ...] | object, *, limit: int) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def route_config_request(state: ConfigState) -> str:
    return "lookup_done" if state.get("response_text") else "call_llm"


def request_approval(state: ApplyChangeState) -> ApplyChangeState:
    return {"approval": str(state.get("approval", ""))}


def finalize_change(state: ApplyChangeState) -> ApplyChangeState:
    approval = state.get("approval", "").lower()
    status = "approved" if approval in {"approve", "approved", "yes"} else "cancelled"
    return {"status": status}


class SimpleWorkflow:
    def __init__(self, nodes: list[Any]) -> None:
        self._nodes = nodes

    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        del config
        current = dict(state)
        runtime = WorkflowRuntime(context=context)
        for node in self._nodes:
            update = node(current, runtime) if _accepts_runtime(node) else node(current)
            if inspect.isawaitable(update):
                update = await update
            if update:
                current.update(update)
        return current


class ConfigWorkflow:
    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        del config
        current = dict(state)
        runtime = WorkflowRuntime(context=context)
        for node in (detect_config_target, collect_config_context):
            update = node(current, runtime) if _accepts_runtime(node) else node(current)
            if inspect.isawaitable(update):
                update = await update
            if update:
                current.update(update)
        for node in (call_config_llm, compose_config_response):
            update = node(current, runtime) if _accepts_runtime(node) else node(current)
            if inspect.isawaitable(update):
                update = await update
            if update:
                current.update(update)
        return current


def _accepts_runtime(node: Any) -> bool:
    return len(inspect.signature(node).parameters) >= 2


def build_diagnosis_graph() -> SimpleWorkflow:
    return SimpleWorkflow([collect_context, run_rules, call_llm, compose_response])


def build_config_graph() -> ConfigWorkflow:
    return ConfigWorkflow()


def build_apply_change_graph() -> SimpleWorkflow:
    return SimpleWorkflow([request_approval, finalize_change])
