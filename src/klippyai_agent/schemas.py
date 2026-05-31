from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, validator
from klippyai_agent.model_compat import BaseModel
from klippyai_agent.printerconfig import ConfigFeature

ArtifactKind = Literal[
    "klippy_log",
    "moonraker_log",
    "system_log",
    "config_snippet",
    "notes",
]
Severity = Literal["low", "medium", "high", "critical"]


class ArtifactInput(BaseModel):
    kind: ArtifactKind = "notes"
    label: str = Field(default="clipboard", min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=40000)

    def prompt_excerpt(self, limit: int = 4000) -> str:
        if len(self.content) <= limit:
            return self.content
        return f"{self.content[:limit]}\n...[truncated]..."


class IssueFinding(BaseModel):
    code: str
    severity: Severity
    source: str
    summary: str
    evidence: str
    proposed_fix: str


class PatchProposal(BaseModel):
    target_file: str
    summary: str
    diff: str
    rationale: str
    safe_mode: str = "review"


class ConfigProposal(BaseModel):
    feature: ConfigFeature = "generic"
    title: str
    target_file: str
    config: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @validator("assumptions", "warnings", pre=True)
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, (list, tuple)):
            value = [value]

        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = _stringify_dict(item)
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


class DetectedAddonSummary(BaseModel):
    name: str
    source: str
    confidence: str = "medium"
    detail: str | None = None


class PrinterProfileSummary(BaseModel):
    firmware_flavor: str | None = None
    firmware_version: str | None = None
    host_model: str | None = None
    host_distribution: str | None = None
    mainboard: str | None = None
    mainboard_mcu: str | None = None
    toolhead: str | None = None
    toolhead_board: str | None = None
    probe_type: str | None = None
    accelerometer: str | None = None
    filament_sensor: str | None = None
    camera_stack: str | None = None
    bed_mesh_configured: bool = False
    input_shaper_configured: bool = False
    printer_state: str | None = None
    canbus_enabled: bool = False
    addons: list[DetectedAddonSummary] = Field(default_factory=list)
    summary: str = ""


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)

    @validator("text", pre=True)
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()


class ChatRequest(BaseModel):
    session_id: str
    thread_id: str | None = None
    message: str = Field(min_length=1, max_length=40000)
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_items=100)


class ChatResponse(BaseModel):
    session_id: str
    thread_id: str
    response: str
    findings: list[IssueFinding]
    next_actions: list[str]
    config_proposals: list[ConfigProposal] = Field(default_factory=list)
    patch_proposals: list[PatchProposal] = Field(default_factory=list)
    provider: str
    moonraker_reachable: bool


class BootstrapResponse(BaseModel):
    session_id: str
    provider: str
    provider_model: str | None = None
    conversation_history_pairs: int = 10
    moonraker_reachable: bool
    klipper_reachable: bool
    expires_at: datetime
    features: list[str]
    printer_profile: PrinterProfileSummary | None = None


class UiSessionResponse(BaseModel):
    session_id: str
    embed_path: str
    expires_at: datetime


def _stringify_dict(value: dict[Any, Any]) -> str:
    for key in ("summary", "text", "message", "description", "value"):
        nested = value.get(key)
        if nested is not None:
            text = str(nested).strip()
            if text:
                return text
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)
