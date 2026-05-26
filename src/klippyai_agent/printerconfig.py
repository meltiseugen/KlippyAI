from __future__ import annotations

import fnmatch
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
ConfigRequestIntent = Literal["generate", "locate"]

_FEATURE_KEYWORDS: tuple[tuple[ConfigFeature, tuple[str, ...]], ...] = (
    ("bed_mesh", ("bed mesh", "bed_mesh", "mesh leveling", "adaptive mesh")),
    ("filament", ("filament sensor", "filament switch", "runout", "motion sensor")),
    ("input_shaper", ("input shaper", "resonance", "adxl", "accelerometer")),
    ("canbus", ("canbus", "can bus", "can toolhead", "ebb", "utoc")),
    ("probe", ("bltouch", "probe", "klicky", "inductive", "cartographer", "beacon", "eddy")),
    ("sensor", ("sensor", "thermistor", "filament switch", "filament sensor")),
    ("macro", ("macro", "gcode_macro", "start print", "end print")),
    ("heater", ("heater", "heater_fan", "temperature_fan", "hotend fan", "bed heater")),
    ("extruder", ("extruder", "rotation_distance", "pressure advance", "pressure_advance")),
    ("stepper", ("stepper", "tmc", "motor current", "driver current", "x axis", "y axis", "z axis")),
    ("fan", ("fan", "blower", "part cooling", "controller fan")),
)
_FEATURE_SECTION_PREFIXES: dict[ConfigFeature, tuple[str, ...]] = {
    "fan": ("fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan"),
    "macro": ("gcode_macro", "delayed_gcode"),
    "sensor": ("temperature_sensor", "thermistor", "adc_temperature"),
    "probe": ("probe", "bltouch", "beacon", "cartographer", "probe_eddy_current"),
    "heater": ("extruder", "heater_bed", "heater_fan", "temperature_fan"),
    "input_shaper": ("input_shaper", "resonance_tester", "adxl345", "lis2dw"),
    "bed_mesh": ("bed_mesh",),
    "filament": ("filament_switch_sensor", "filament_motion_sensor"),
    "canbus": ("mcu",),
    "stepper": ("stepper_", "tmc"),
    "extruder": ("extruder", "extruder_stepper"),
    "generic": (),
}
_DIRECT_SECTION_PATTERN = re.compile(r"\[([^\]]+)\]")
_SECTION_LINE_PATTERN = re.compile(r"^\s*\[[^\]\n]+\]\s*$")


@dataclass(slots=True)
class ConfigDocument:
    path: str
    content: str
    sections: list[str]

    def prompt_block(self) -> str:
        section_text = ", ".join(self.sections[:12]) if self.sections else "no sections detected"
        return f"File: {self.path}\nSections: {section_text}\n\n{self.content}"


@dataclass(frozen=True, slots=True)
class ConfigPlaceholder:
    path: str
    line_number: int
    line_text: str
    value: str
    section: str | None = None
    option: str | None = None

    def summary(self) -> str:
        details: list[str] = [f"{self.value} at {self.path}:{self.line_number}"]
        if self.section:
            details.append(f"section [{self.section}]")
        if self.option:
            details.append(f"option {self.option}")
        return " | ".join(details)


@dataclass(frozen=True, slots=True)
class ConfigSectionLocation:
    path: str
    line_number: int
    section: str

    def summary(self) -> str:
        return f"[{self.section}] at {self.path}:{self.line_number}"


@dataclass(slots=True)
class ConfigSnapshot:
    root_file: str | None
    documents: list[ConfigDocument]
    section_locations: list[ConfigSectionLocation] = field(default_factory=list)
    placeholders: list[ConfigPlaceholder] = field(default_factory=list)
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

    def find_section_locations(
        self,
        target: "ConfigRequestTarget",
        *,
        limit: int = 12,
    ) -> list[ConfigSectionLocation]:
        if target.section_name:
            matches = [
                location
                for location in self.section_locations
                if location.section.lower() == target.section_name.lower()
            ]
            return matches[:limit]

        prefixes = _FEATURE_SECTION_PREFIXES.get(target.feature, ())
        matches = [
            location
            for location in self.section_locations
            if any(_section_matches_prefix(location.section, prefix) for prefix in prefixes)
        ]
        return matches[:limit]

    def section_block(self, location: ConfigSectionLocation) -> str | None:
        document = next((item for item in self.documents if item.path == location.path), None)
        if document is None:
            return None

        lines = document.content.splitlines()
        start_index = max(location.line_number - 1, 0)
        if start_index >= len(lines):
            return None

        end_index = len(lines)
        for index in range(start_index + 1, len(lines)):
            if _SECTION_LINE_PATTERN.match(lines[index]):
                end_index = index
                break

        block = "\n".join(lines[start_index:end_index]).rstrip()
        return block or None

    def to_prompt_block(self, max_documents: int | None = None) -> str:
        sections: list[str] = []
        if self.root_file:
            sections.append(f"Root config: {self.root_file}")
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))
        if self.placeholders:
            placeholder_lines = [f"- {placeholder.summary()}" for placeholder in self.placeholders[:6]]
            sections.append("Detected placeholder values:\n" + "\n".join(placeholder_lines))
        if self.documents:
            documents = self.documents if max_documents is None else self.documents[:max_documents]
            document_blocks = [document.prompt_block() for document in documents]
            sections.append("Config files:\n" + "\n\n".join(document_blocks))
        else:
            sections.append("No config files were collected.")
        return "\n\n".join(sections)

    def to_state(self) -> dict[str, Any]:
        return {
            "root_file": self.root_file,
            "notes": list(self.notes),
            "section_locations": [
                {
                    "path": location.path,
                    "line_number": location.line_number,
                    "section": location.section,
                }
                for location in self.section_locations
            ],
            "placeholders": [
                {
                    "path": placeholder.path,
                    "line_number": placeholder.line_number,
                    "line_text": placeholder.line_text,
                    "value": placeholder.value,
                    "section": placeholder.section,
                    "option": placeholder.option,
                }
                for placeholder in self.placeholders
            ],
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
        section_locations = [
            ConfigSectionLocation(
                path=str(item.get("path", "")),
                line_number=int(item.get("line_number", 0)),
                section=str(item.get("section", "")),
            )
            for item in data.get("section_locations", [])
        ]
        placeholders = [
            ConfigPlaceholder(
                path=str(item.get("path", "")),
                line_number=int(item.get("line_number", 0)),
                line_text=str(item.get("line_text", "")),
                value=str(item.get("value", "")),
                section=str(item["section"]) if item.get("section") else None,
                option=str(item["option"]) if item.get("option") else None,
            )
            for item in data.get("placeholders", [])
        ]
        root_file = data.get("root_file")
        return cls(
            root_file=str(root_file) if root_file else None,
            documents=documents,
            section_locations=section_locations,
            placeholders=placeholders,
            notes=[str(note) for note in data.get("notes", [])],
        )


@dataclass(frozen=True, slots=True)
class ConfigRequestTarget:
    feature: ConfigFeature
    rationale: str
    intent: ConfigRequestIntent = "generate"
    section_name: str | None = None


class ConfigCollector:
    _INCLUDE_PATTERN = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*$", re.IGNORECASE | re.MULTILINE)
    _SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$", re.MULTILINE)
    _OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$")
    _PLACEHOLDER_VALUE_PATTERN = re.compile(r"^(YOUR_[A-Z0-9_]+|<[A-Z0-9_]+>)$")

    def __init__(
        self,
        printer_data_root: Path,
        *,
        config_dir_name: str = "config",
        root_config_name: str | None = None,
        ignore_globs: str | list[str] | tuple[str, ...] | None = None,
        max_documents: int | None = None,
        max_chars_per_document: int | None = None,
    ) -> None:
        self._config_dir = printer_data_root / config_dir_name
        self._root_config_name = self._normalize_root_config_name(root_config_name)
        self._ignore_globs = self._normalize_ignore_globs(ignore_globs)
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

        root_file = self._resolve_root_file(notes)
        if root_file is None:
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        visited: set[Path] = set()
        documents: list[ConfigDocument] = []
        section_locations: list[ConfigSectionLocation] = []
        placeholders: list[ConfigPlaceholder] = []
        self._collect_file(root_file, visited, documents, section_locations, placeholders, notes)
        if self._max_documents is not None and len(documents) >= self._max_documents:
            notes.append(f"Config collection stopped after {self._max_documents} files to keep context bounded.")

        return ConfigSnapshot(
            root_file=str(root_file),
            documents=documents,
            section_locations=section_locations,
            placeholders=placeholders,
            notes=notes,
        )

    @staticmethod
    def _normalize_root_config_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_ignore_globs(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            parts = [item.strip() for item in re.split(r"[,\n;]+", value) if item.strip()]
            return tuple(parts)
        return tuple(str(item).strip() for item in value if str(item).strip())

    def _resolve_root_file(self, notes: list[str]) -> Path | None:
        if self._root_config_name:
            root_file = self._resolve_root_candidate(self._root_config_name)
            if not root_file.exists():
                notes.append(f"Configured root config file was not found: {root_file}")
                return None
            if not root_file.is_file():
                notes.append(f"Configured root config path is not a file: {root_file}")
                return None
            return root_file

        auto_detected = self._auto_detect_root_file()
        if auto_detected is None:
            notes.append(f"No root config file could be auto-detected under: {self._config_dir}")
            return None
        notes.append(f"Auto-detected root config file: {auto_detected}")
        return auto_detected

    def _resolve_root_candidate(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return self._config_dir / candidate

    def _auto_detect_root_file(self) -> Path | None:
        candidates = [
            path
            for path in self._config_dir.rglob("*.cfg")
            if path.is_file() and not self._should_ignore(path)
        ]
        if not candidates:
            return None

        ranked: list[tuple[int, Path]] = []
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            sections = self._extract_sections(content)
            includes = self._extract_include_patterns(content)
            score = 0
            if path.name.lower() == "printer.cfg":
                score += 8
            if path.parent == self._config_dir:
                score += 3
            if any(section.lower() == "printer" for section in sections):
                score += 12
            score += min(len(includes), 5)
            ranked.append((score, path))

        if not ranked:
            return None

        ranked.sort(key=lambda item: (item[0], str(item[1]).lower()), reverse=True)
        return ranked[0][1]

    def _collect_file(
        self,
        path: Path,
        visited: set[Path],
        documents: list[ConfigDocument],
        section_locations: list[ConfigSectionLocation],
        placeholders: list[ConfigPlaceholder],
        notes: list[str],
    ) -> None:
        if self._max_documents is not None and len(documents) >= self._max_documents:
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
        section_locations.extend(self._extract_section_locations(path, raw_content))
        placeholders.extend(self._detect_placeholders(path, raw_content))
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
                if self._should_ignore(match):
                    notes.append(f"Ignored config file due to config_context.ignore_globs: {match}")
                    continue
                self._collect_file(match, visited, documents, section_locations, placeholders, notes)
                if self._max_documents is not None and len(documents) >= self._max_documents:
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

    def _should_ignore(self, path: Path) -> bool:
        if not self._ignore_globs:
            return False
        relative = self._relative_path_string(path)
        path_name = path.name
        absolute = path.as_posix()
        return any(
            fnmatch.fnmatch(relative, pattern)
            or fnmatch.fnmatch(path_name, pattern)
            or fnmatch.fnmatch(absolute, pattern)
            for pattern in self._ignore_globs
        )

    def _relative_path_string(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._config_dir.resolve()).as_posix()
        except (OSError, ValueError):
            try:
                return path.relative_to(self._config_dir).as_posix()
            except ValueError:
                return path.as_posix()

    @staticmethod
    def _clip_text(text: str, limit: int | None) -> str:
        if limit is None or len(text) <= limit:
            return text

        head = max((limit - 32) // 2, 0)
        tail = max(limit - head - 17, 0)
        return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"

    @classmethod
    def _extract_section_locations(cls, path: Path, content: str) -> list[ConfigSectionLocation]:
        locations: list[ConfigSectionLocation] = []

        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            section_match = cls._SECTION_PATTERN.match(raw_line)
            if not section_match:
                continue

            section = section_match.group(1).strip()
            if section.lower().startswith("include "):
                continue

            locations.append(
                ConfigSectionLocation(
                    path=str(path),
                    line_number=line_number,
                    section=section,
                )
            )

        return locations

    @classmethod
    def _detect_placeholders(cls, path: Path, content: str) -> list[ConfigPlaceholder]:
        placeholders: list[ConfigPlaceholder] = []
        current_section: str | None = None

        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            section_match = cls._SECTION_PATTERN.match(raw_line)
            if section_match:
                section = section_match.group(1).strip()
                if not section.lower().startswith("include "):
                    current_section = section
                continue

            normalized_line = raw_line.split("#", 1)[0].strip()
            if not normalized_line:
                continue

            option_match = cls._OPTION_PATTERN.match(normalized_line)
            if not option_match:
                continue

            option = option_match.group(1).strip()
            value = option_match.group(2).strip()
            unquoted_value = value.strip("\"'")
            if not cls._PLACEHOLDER_VALUE_PATTERN.fullmatch(unquoted_value):
                continue

            placeholders.append(
                ConfigPlaceholder(
                    path=str(path),
                    line_number=line_number,
                    line_text=normalized_line,
                    value=unquoted_value,
                    section=current_section,
                    option=option,
                )
            )

        return placeholders


def infer_config_request_target(message: str) -> ConfigRequestTarget:
    lowered = message.lower()

    explicit_section = _extract_explicit_section_name(message)
    if explicit_section:
        feature = _infer_feature_from_section_name(explicit_section)
        return ConfigRequestTarget(
            feature=feature,
            rationale=f"Matched explicit section lookup for [{explicit_section}].",
            intent="locate",
            section_name=explicit_section,
        )

    for feature, keywords in _FEATURE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return ConfigRequestTarget(
                feature=feature,
                rationale=f"Matched request keywords for {feature}.",
                intent="locate" if _looks_like_lookup_request(lowered) else "generate",
            )

    return ConfigRequestTarget(
        feature="generic",
        rationale="No specific supported config feature was detected from the request text.",
    )


def looks_like_config_request(message: str) -> bool:
    lowered = message.lower()
    generate_intent_words = (
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
    lookup_intent_words = (
        "where",
        "which file",
        "what file",
        "find",
        "locate",
        "show me where",
        "defined",
        "configured",
        "declared",
    )
    if _extract_explicit_section_name(message):
        return True

    has_generate_intent = any(word in lowered for word in generate_intent_words)
    has_lookup_intent = any(word in lowered for word in lookup_intent_words) or _looks_like_section_content_request(lowered)
    has_feature = any(keyword in lowered for _, keywords in _FEATURE_KEYWORDS for keyword in keywords)
    return has_feature and (has_generate_intent or has_lookup_intent)


def build_config_lookup_response(
    snapshot: ConfigSnapshot,
    target: ConfigRequestTarget,
    *,
    include_content: bool = False,
) -> tuple[str, list[str]]:
    matches = snapshot.find_section_locations(target)
    label = _describe_lookup_target(target)

    if matches:
        noun = "section" if len(matches) == 1 else "sections"
        lines = [f"I found {len(matches)} active {label} {noun} in the current config tree.", "", "Matches:"]
        lines.extend(f"- {match.summary()}" for match in matches)
        next_actions: list[str] = []
        if len(matches) > 1:
            next_actions.append("Ask for an exact section name if you want one match narrowed further.")
        elif include_content:
            block = snapshot.section_block(matches[0])
            if block:
                lines.extend(["", "Config:", "```ini", block, "```"])
        return "\n".join(lines), next_actions

    lines = [f"I couldn't find any active {label} sections in the current config tree."]
    next_actions = [
        "Ask for the exact section name if you know it, for example [extruder] or [fan_generic part_cooling].",
        "Check whether the section lives in an include path outside the collected config tree.",
    ]
    return "\n".join(lines), next_actions


def _looks_like_lookup_request(lowered_message: str) -> bool:
    lookup_intent_words = (
        "where",
        "which file",
        "what file",
        "find",
        "locate",
        "show me where",
        "defined",
        "configured",
        "declared",
    )
    return any(word in lowered_message for word in lookup_intent_words) or _looks_like_section_content_request(lowered_message)


def looks_like_config_content_request(message: str) -> bool:
    return _looks_like_section_content_request(message.lower())


def _looks_like_section_content_request(lowered_message: str) -> bool:
    content_intent_words = (
        "show",
        "show me",
        "give me",
        "paste",
        "print",
        "display",
        "what is in",
    )
    section_words = (
        "section",
        "block",
        "definition",
        "defined",
        "current",
        "existing",
        "here",
    )
    return any(word in lowered_message for word in content_intent_words) and any(
        word in lowered_message for word in section_words
    )


def _extract_explicit_section_name(message: str) -> str | None:
    match = _DIRECT_SECTION_PATTERN.search(message)
    if not match:
        return None
    section = match.group(1).strip()
    return section or None


def _infer_feature_from_section_name(section_name: str) -> ConfigFeature:
    lowered = section_name.lower()
    for feature, prefixes in _FEATURE_SECTION_PREFIXES.items():
        if any(_section_matches_prefix(lowered, prefix) for prefix in prefixes):
            return feature
    return "generic"


def _section_matches_prefix(section_name: str, prefix: str) -> bool:
    lowered_section = section_name.lower()
    lowered_prefix = prefix.lower()
    if lowered_prefix.endswith("_"):
        return lowered_section.startswith(lowered_prefix)
    if lowered_section == lowered_prefix:
        return True
    if not lowered_section.startswith(lowered_prefix):
        return False
    next_char = lowered_section[len(lowered_prefix) : len(lowered_prefix) + 1]
    return next_char in {"", " ", "_"} or next_char.isdigit()


def _describe_lookup_target(target: ConfigRequestTarget) -> str:
    if target.section_name:
        return f"[{target.section_name}]"
    labels = {
        "fan": "fan-related",
        "macro": "macro-related",
        "sensor": "sensor-related",
        "probe": "probe-related",
        "heater": "heater-related",
        "input_shaper": "input-shaper-related",
        "bed_mesh": "bed-mesh-related",
        "filament": "filament-sensor-related",
        "canbus": "CAN-related",
        "stepper": "stepper-related",
        "extruder": "extruder-related",
        "generic": "matching",
    }
    return labels.get(target.feature, "matching")
