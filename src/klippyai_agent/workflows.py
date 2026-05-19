from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from klippyai_agent.diagnostics import DiagnosticsCollector, DiagnosticsSnapshot, RuleEngine
from klippyai_agent.llm import (
    ConfigAssistantProvider,
    ConfigPromptPayload,
    DiagnosisPromptPayload,
    DiagnosisProvider,
)
from klippyai_agent.printerconfig import (
    ConfigCollector,
    ConfigRequestTarget,
    ConfigSnapshot,
    infer_config_request_target,
)
from klippyai_agent.printerprofile import PrinterProfile
from klippyai_agent.schemas import ArtifactInput, ConfigProposal, IssueFinding


@dataclass(slots=True)
class WorkflowContext:
    collector: DiagnosticsCollector
    rules: RuleEngine
    llm: DiagnosisProvider
    config_collector: ConfigCollector
    config_llm: ConfigAssistantProvider
    profile: PrinterProfile


class DiagnosisState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_message: str
    artifacts: list[dict[str, Any]]
    snapshot: dict[str, Any]
    config_snapshot: dict[str, Any]
    findings: list[dict[str, Any]]
    llm_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    moonraker_reachable: bool
    patch_proposals: list[dict[str, Any]]


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
    feature_target: dict[str, Any]
    config_snapshot: dict[str, Any]
    config_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    config_proposals: list[dict[str, Any]]


async def collect_context(
    state: DiagnosisState,
    runtime: Runtime[WorkflowContext],
) -> DiagnosisState:
    input_artifacts = [ArtifactInput.model_validate(item) for item in state.get("artifacts", [])]
    snapshot = await runtime.context.collector.collect(input_artifacts)
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
    runtime: Runtime[WorkflowContext],
) -> DiagnosisState:
    snapshot_data = state.get("snapshot", {})
    artifact_items = snapshot_data.get("artifacts", state.get("artifacts", []))
    artifacts = [ArtifactInput.model_validate(item) for item in artifact_items]
    findings = runtime.context.rules.analyze(artifacts)
    return {
        "findings": [finding.model_dump() for finding in findings],
        "patch_proposals": [],
    }


async def call_llm(
    state: DiagnosisState,
    runtime: Runtime[WorkflowContext],
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
    summary = llm_output.get("summary", "No summary available.")
    likely_causes = llm_output.get("likely_causes", [])
    recommended_actions = llm_output.get("recommended_actions", [])
    follow_up_questions = llm_output.get("follow_up_questions", [])

    lines = [summary]

    if findings:
        lines.append("")
        lines.append("Evidence-backed findings:")
        for finding in findings[:5]:
            lines.append(f"- [{finding['severity']}] {finding['summary']}")

    if likely_causes:
        lines.append("")
        lines.append("Likely causes:")
        for item in likely_causes[:5]:
            lines.append(f"- {item}")

    if recommended_actions:
        lines.append("")
        lines.append("Recommended next actions:")
        for item in recommended_actions[:5]:
            lines.append(f"- {item}")

    if follow_up_questions:
        lines.append("")
        lines.append("Follow-up questions:")
        for item in follow_up_questions[:3]:
            lines.append(f"- {item}")

    next_actions = recommended_actions or [finding["proposed_fix"] for finding in findings[:3]]
    return {
        "response_text": "\n".join(lines).strip(),
        "next_actions": next_actions,
    }


def detect_config_target(state: ConfigState) -> ConfigState:
    target = infer_config_request_target(state["user_message"])
    return {
        "feature_target": {
            "feature": target.feature,
            "rationale": target.rationale,
        }
    }


async def collect_config_context(
    state: ConfigState,
    runtime: Runtime[WorkflowContext],
) -> ConfigState:
    snapshot = runtime.context.config_collector.collect()
    return {
        "config_snapshot": snapshot.to_state(),
    }


async def call_config_llm(
    state: ConfigState,
    runtime: Runtime[WorkflowContext],
) -> ConfigState:
    target_data = state.get("feature_target", {})
    snapshot_data = state.get("config_snapshot", {})
    detected = infer_config_request_target(state["user_message"])
    target = ConfigRequestTarget(
        feature=target_data.get("feature", detected.feature),
        rationale=target_data.get("rationale", detected.rationale),
    )

    snapshot = ConfigSnapshot.from_state(snapshot_data)
    payload = ConfigPromptPayload(
        user_message=state["user_message"],
        snapshot=snapshot,
        target=target,
        profile=runtime.context.profile,
    )
    config_output = await runtime.context.config_llm.propose(payload)
    return {"config_output": config_output.model_dump()}


def compose_config_response(state: ConfigState) -> ConfigState:
    output = state.get("config_output", {})
    summary = output.get("summary", "No config proposal was generated.")
    proposals = [ConfigProposal.model_validate(item) for item in output.get("proposals", [])]
    next_actions = list(output.get("next_actions", []))
    follow_up_questions = list(output.get("follow_up_questions", []))

    lines = [summary]

    if proposals:
        lines.append("")
        lines.append("Generated config proposals:")
        for proposal in proposals:
            lines.append(f"- {proposal.title} -> {proposal.target_file}")
            lines.append("")
            lines.append(f"```ini\n{proposal.config}\n```")
            if proposal.assumptions:
                lines.append("Assumptions:")
                for item in proposal.assumptions[:4]:
                    lines.append(f"- {item}")
            if proposal.warnings:
                lines.append("Warnings:")
                for item in proposal.warnings[:4]:
                    lines.append(f"- {item}")

    if next_actions:
        lines.append("")
        lines.append("Next actions:")
        for item in next_actions[:5]:
            lines.append(f"- {item}")

    if follow_up_questions:
        lines.append("")
        lines.append("Follow-up questions:")
        for item in follow_up_questions[:3]:
            lines.append(f"- {item}")

    return {
        "response_text": "\n".join(lines).strip(),
        "next_actions": next_actions,
        "config_proposals": [proposal.model_dump() for proposal in proposals],
    }


def request_approval(state: ApplyChangeState) -> ApplyChangeState:
    decision = interrupt(
        {
            "target_file": state["target_file"],
            "diff": state["diff"],
            "rationale": state["rationale"],
        }
    )
    return {"approval": str(decision)}


def finalize_change(state: ApplyChangeState) -> ApplyChangeState:
    approval = state.get("approval", "").lower()
    status = "approved" if approval in {"approve", "approved", "yes"} else "cancelled"
    return {"status": status}


def build_diagnosis_graph(checkpointer: Any):
    graph = StateGraph(DiagnosisState, context_schema=WorkflowContext)
    graph.add_node("collect_context", collect_context)
    graph.add_node("run_rules", run_rules)
    graph.add_node("call_llm", call_llm)
    graph.add_node("compose_response", compose_response)
    graph.add_edge(START, "collect_context")
    graph.add_edge("collect_context", "run_rules")
    graph.add_edge("run_rules", "call_llm")
    graph.add_edge("call_llm", "compose_response")
    graph.add_edge("compose_response", END)
    return graph.compile(checkpointer=checkpointer)


def build_config_graph(checkpointer: Any):
    graph = StateGraph(ConfigState, context_schema=WorkflowContext)
    graph.add_node("detect_config_target", detect_config_target)
    graph.add_node("collect_config_context", collect_config_context)
    graph.add_node("call_config_llm", call_config_llm)
    graph.add_node("compose_config_response", compose_config_response)
    graph.add_edge(START, "detect_config_target")
    graph.add_edge("detect_config_target", "collect_config_context")
    graph.add_edge("collect_config_context", "call_config_llm")
    graph.add_edge("call_config_llm", "compose_config_response")
    graph.add_edge("compose_config_response", END)
    return graph.compile(checkpointer=checkpointer)


def build_apply_change_graph(checkpointer: Any):
    graph = StateGraph(ApplyChangeState)
    graph.add_node("request_approval", request_approval)
    graph.add_node("finalize_change", finalize_change)
    graph.add_edge(START, "request_approval")
    graph.add_edge("request_approval", "finalize_change")
    graph.add_edge("finalize_change", END)
    return graph.compile(checkpointer=checkpointer)
