from __future__ import annotations

import re
from typing import Any, Literal, Protocol

from pydantic import Field, validator

from klippyai_agent.model_compat import BaseModel
from klippyai_agent.printerconfig import infer_config_request_target, looks_like_config_request


ChatIntentName = Literal[
    "config_lookup",
    "config_explain",
    "diagnose_issue",
    "generate_config",
    "edit_existing_config",
    "general",
]
ChatRoute = Literal["config", "diagnostics"]

_DIAGNOSIS_WORDS = (
    "adc out of range",
    "broken",
    "can't",
    "cannot",
    "crash",
    "does not work",
    "doesn't work",
    "error",
    "failed",
    "failing",
    "fail",
    "issue",
    "mcu shutdown",
    "not working",
    "problem",
    "shutdown",
    "timer too close",
    "unable to",
    "won't",
)


class ChatIntentOutput(BaseModel):
    intent: ChatIntentName = "general"
    target: str | None = None
    target_section: str | None = None
    needs_logs: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""

    @validator("intent", pre=True)
    def _normalize_intent(cls, value: Any) -> str:
        normalized = str(value or "general").strip().lower().replace("-", "_").replace(" ", "_")
        allowed = set(ChatIntentName.__args__)
        aliases = {
            "lookup": "config_lookup",
            "config": "generate_config",
            "config_generation": "generate_config",
            "diagnostics": "diagnose_issue",
            "diagnosis": "diagnose_issue",
            "debug": "diagnose_issue",
            "explain": "config_explain",
            "edit": "edit_existing_config",
        }
        return aliases.get(normalized, normalized if normalized in allowed else "general")

    @validator("target", "target_section", pre=True)
    def _normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @validator("rationale", pre=True)
    def _normalize_rationale(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @validator("needs_logs", pre=True, always=True)
    def _normalize_needs_logs(cls, value: Any, values: dict[str, Any]) -> bool:
        return bool(value) or values.get("intent") == "diagnose_issue"


class IntentRouterProvider(Protocol):
    name: str

    async def classify(self, message: str) -> ChatIntentOutput:
        ...


def classify_deterministic_intent(message: str) -> ChatIntentOutput:
    lowered = message.lower()
    target = infer_config_request_target(message)

    if _looks_like_diagnostic_request(lowered):
        return ChatIntentOutput(
            intent="diagnose_issue",
            needs_logs=True,
            confidence=0.9,
            rationale="Matched diagnostic failure/problem language.",
        )

    if target.intent == "locate":
        return ChatIntentOutput(
            intent="config_lookup",
            target=target.section_name,
            target_section=target.section_name,
            needs_logs=False,
            confidence=0.95 if target.section_name else 0.86,
            rationale=target.rationale,
        )

    if target.intent == "explain":
        return ChatIntentOutput(
            intent="config_explain",
            target=target.section_name,
            target_section=target.section_name,
            needs_logs=False,
            confidence=0.9 if target.section_name else 0.8,
            rationale=target.rationale,
        )

    if target.intent == "edit":
        return ChatIntentOutput(
            intent="edit_existing_config",
            target=target.section_name,
            target_section=target.section_name,
            needs_logs=False,
            confidence=0.84,
            rationale=target.rationale,
        )

    if looks_like_config_request(message):
        return ChatIntentOutput(
            intent="generate_config",
            needs_logs=False,
            confidence=0.84,
            rationale=target.rationale,
        )

    return ChatIntentOutput(
        intent="general",
        needs_logs=False,
        confidence=0.45,
        rationale="No deterministic config or diagnostic intent matched.",
    )


def route_for_intent(intent: ChatIntentOutput) -> ChatRoute:
    if intent.intent in {"config_lookup", "config_explain", "generate_config", "edit_existing_config"}:
        return "config"
    return "diagnostics"


def _looks_like_diagnostic_request(lowered_message: str) -> bool:
    return any(word in lowered_message for word in _DIAGNOSIS_WORDS) or bool(
        re.search(r"\bwhy\b.+\b(fail|failed|failing|error|shutdown|stopped|broken)\b", lowered_message)
    )
