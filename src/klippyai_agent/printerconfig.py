from __future__ import annotations

import glob
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ConfigFeature = Literal[
    "fan",
    "macro",
    "sensor",
    "probe",
    "heater",
    "input_shaper",
    "bed_mesh",
    "filament",
    "canbus",
    "stepper",
    "extruder",
    "generic",
]


@dataclass(slots=True)
class ConfigDocument:
    path: str
    content: str
    sections: list[str]

    def prompt_block(self) -> str:
        section_text = ", ".join(self.sections[:12]) if self.sections else "no sections detected"
        return f"File: {self.path}\nSections: {section_text}\n\n{self.content}"


@dataclass(slots=True)
class ConfigSnapshot:
    root_file: str | None
    documents: list[ConfigDocument]
    notes: list[str] = field(default_factory=list)

    @property
    def section_names(self) -> list[str]:
        names: list[str] = []
        for document in self.documents:
            names.extend(document.sections)
        return names

    def has_section_prefix(self, prefix: str) -> bool:
        prefix_lower = prefix.lower()
        return any(section.lower().startswith(prefix_lower) for section in self.section_names)

    def has_managed_include(self, include_name: str = "klippyai") -> bool:
        include_pattern = re.compile(
            rf"^\s*\[include\s+.*{re.escape(include_name)}.*\]\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        return any(include_pattern.search(document.content) for document in self.documents)

    def to_prompt_block(self, max_documents: int = 8) -> str:
        sections: list[str] = []
        if self.root_file:
            sections.append(f"Root config: {self.root_file}")
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))
        if self.documents:
            document_blocks = [document.prompt_block() for document in self.documents[:max_documents]]
            sections.append("Config files:\n" + "\n\n".join(document_blocks))
        else:
            sections.append("No config files were collected.")
        return "\n\n".join(sections)

    def to_state(self) -> dict[str, Any]:
        return {
            "root_file": self.root_file,
            "notes": list(self.notes),
            "documents": [
                {
                    "path": document.path,
                    "content": document.content,
                    "sections": list(document.sections),
                }
                for document in self.documents
            ],
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> ConfigSnapshot:
        documents = [
            ConfigDocument(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                sections=[str(section) for section in item.get("sections", [])],
            )
            for item in data.get("documents", [])
        ]
        root_file = data.get("root_file")
        return cls(
            root_file=str(root_file) if root_file else None,
            documents=documents,
            notes=[str(note) for note in data.get("notes", [])],
        )


@dataclass(frozen=True, slots=True)
class ConfigRequestTarget:
    feature: ConfigFeature
    rationale: str


class ConfigCollector:
    _INCLUDE_PATTERN = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*$", re.IGNORECASE | re.MULTILINE)
    _SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$", re.MULTILINE)

    def __init__(
        self,
        printer_data_root: Path,
        *,
        config_dir_name: str = "config",
        root_config_name: str = "printer.cfg",
        max_documents: int = 12,
        max_chars_per_document: int = 12_000,
    ) -> None:
        self._config_dir = printer_data_root / config_dir_name
        self._root_config_name = root_config_name
        self._max_documents = max_documents
        self._max_chars_per_document = max_chars_per_document

    def collect(self) -> ConfigSnapshot:
        notes: list[str] = []
        if not self._config_dir.exists():
            notes.append(f"Config directory does not exist: {self._config_dir}")
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        if not self._config_dir.is_dir():
            notes.append(f"Config path is not a directory: {self._config_dir}")
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        root_file = self._config_dir / self._root_config_name
        if not root_file.exists():
            notes.append(f"Root config file was not found: {root_file}")
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        visited: set[Path] = set()
        documents: list[ConfigDocument] = []
        self._collect_file(root_file, visited, documents, notes)
        if len(documents) >= self._max_documents:
            notes.append(f"Config collection stopped after {self._max_documents} files to keep context bounded.")

        return ConfigSnapshot(
            root_file=str(root_file),
            documents=documents,
            notes=notes,
        )

    def _collect_file(
        self,
        path: Path,
        visited: set[Path],
        documents: list[ConfigDocument],
        notes: list[str],
    ) -> None:
        if len(documents) >= self._max_documents:
            return

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        if resolved in visited:
            return
        visited.add(resolved)

        try:
            raw_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"Could not read config file {path}: {exc}")
            return

        sections = self._extract_sections(raw_content)
        clipped_content = self._clip_text(raw_content.strip(), self._max_chars_per_document)
        documents.append(
            ConfigDocument(
                path=str(path),
                content=clipped_content,
                sections=sections,
            )
        )

        for pattern in self._extract_include_patterns(raw_content):
            matches = self._resolve_include_matches(path.parent, pattern)
            if not matches:
                notes.append(f"Include pattern matched no files: {pattern} (from {path.name})")
                continue
            for match in matches:
                self._collect_file(match, visited, documents, notes)
                if len(documents) >= self._max_documents:
                    return

    @classmethod
    def _extract_include_patterns(cls, content: str) -> list[str]:
        return [match.group(1).strip().strip("\"'") for match in cls._INCLUDE_PATTERN.finditer(content)]

    @classmethod
    def _extract_sections(cls, content: str) -> list[str]:
        sections: list[str] = []
        for match in cls._SECTION_PATTERN.finditer(content):
            section = match.group(1).strip()
            if section.lower().startswith("include "):
                continue
            sections.append(section)
        return sections

    @staticmethod
    def _resolve_include_matches(base_dir: Path, pattern: str) -> list[Path]:
        expanded_pattern = str((base_dir / pattern).expanduser())
        matches = [
            Path(candidate)
            for candidate in sorted(glob.glob(expanded_pattern, recursive=True))
            if Path(candidate).is_file()
        ]
        return matches

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text

        head = max((limit - 32) // 2, 0)
        tail = max(limit - head - 17, 0)
        return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"


def infer_config_request_target(message: str) -> ConfigRequestTarget:
    lowered = message.lower()

    keyword_map: list[tuple[ConfigFeature, tuple[str, ...]]] = [
        ("bed_mesh", ("bed mesh", "bed_mesh", "mesh leveling", "adaptive mesh")),
        ("filament", ("filament sensor", "filament switch", "runout", "motion sensor")),
        ("input_shaper", ("input shaper", "resonance", "adxl", "accelerometer")),
        ("canbus", ("canbus", "can bus", "can toolhead", "ebb", "utoc")),
        ("probe", ("bltouch", "probe", "klicky", "inductive", "cartographer")),
        ("sensor", ("sensor", "thermistor", "filament switch", "filament sensor")),
        ("macro", ("macro", "gcode_macro", "start print", "end print")),
        ("heater", ("heater", "heater_fan", "temperature_fan", "hotend fan", "bed heater")),
        ("extruder", ("extruder", "rotation_distance", "pressure advance", "pressure_advance")),
        ("stepper", ("stepper", "tmc", "motor current", "driver current", "x axis", "y axis", "z axis")),
        ("fan", ("fan", "blower", "part cooling", "controller fan")),
    ]

    for feature, keywords in keyword_map:
        if any(keyword in lowered for keyword in keywords):
            return ConfigRequestTarget(
                feature=feature,
                rationale=f"Matched request keywords for {feature}.",
            )

    return ConfigRequestTarget(
        feature="generic",
        rationale="No specific supported config feature was detected from the request text.",
    )


def looks_like_config_request(message: str) -> bool:
    lowered = message.lower()
    intent_words = (
        "add",
        "generate",
        "create",
        "write",
        "make",
        "build",
        "draft",
        "propose",
        "configure",
        "config",
        "cfg",
        "setup",
        "set up",
        "define",
        "improve",
        "optimize",
        "rewrite",
    )
    feature_words = (
        "fan",
        "macro",
        "sensor",
        "probe",
        "heater",
        "input shaper",
        "bed mesh",
        "filament",
        "canbus",
        "can bus",
        "extruder",
        "stepper",
        "tmc",
        "pressure advance",
        "printer.cfg",
        "klipper config",
    )

    has_intent = any(word in lowered for word in intent_words)
    has_feature = any(word in lowered for word in feature_words)
    return has_intent and has_feature
