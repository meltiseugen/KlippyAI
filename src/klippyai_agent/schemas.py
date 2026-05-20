from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
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


class ChatRequest(BaseModel):
    session_id: str
    thread_id: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    artifacts: list[ArtifactInput] = Field(default_factory=list)


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
    moonraker_reachable: bool
    expires_at: datetime
    features: list[str]
    printer_profile: PrinterProfileSummary | None = None


class UiSessionResponse(BaseModel):
    session_id: str
    embed_path: str
    expires_at: datetime
