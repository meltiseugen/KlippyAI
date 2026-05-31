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
ConfigRequestIntent = Literal["generate", "locate", "explain", "edit"]

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
_MACRO_WORD_PATTERN = re.compile(r"\b(?:gcode[_\s-]*)?macro\b(?!-)", re.IGNORECASE)
_MACRO_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+\b")
_MACRO_COMMAND_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
_MACRO_NAME_BOUNDARY_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "can",
    "configured",
    "declared",
    "defined",
    "definition",
    "do",
    "does",
    "file",
    "find",
    "for",
    "gcode",
    "has",
    "have",
    "i",
    "in",
    "is",
    "locate",
    "located",
    "macro",
    "me",
    "my",
    "on",
    "please",
    "show",
    "that",
    "the",
    "this",
    "what",
    "where",
    "which",
    "you",
    "your",
}
_MACRO_NAME_LEADING_WORDS = {
    "called",
    "named",
    "is",
    "as",
    "for",
    "the",
    "my",
    "a",
    "an",
}
_LOOKUP_CORRECTION_WORDS = ("i mean", "i meant", "actually", "rather", "instead", "sorry")
_EXPLAIN_INTENT_WORDS = (
    "called by",
    "explain",
    "how does",
    "tell me about",
    "used by",
    "what does",
    "what is",
    "where is used",
    "where is it used",
)
_EDIT_INTENT_WORDS = (
    "change",
    "disable",
    "edit",
    "enable",
    "modify",
    "remove",
    "rename",
    "replace",
    "turn off",
    "turn on",
    "update",
)


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


@dataclass(frozen=True, slots=True)
class _ConfigLineReference:
    path: str
    line_number: int
    section: str | None
    line_text: str

    def summary(self) -> str:
        location = f"{self.path}:{self.line_number}"
        section = f"[{self.section}]" if self.section else "top level"
        return f"{section} at {location}: `{_inline_code(self.line_text)}`"


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
            requested_key = _normalize_section_lookup_key(target.section_name)
            matches = [
                location
                for location in self.section_locations
                if location.section.lower() == target.section_name.lower()
                or _normalize_section_lookup_key(location.section) == requested_key
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
        sections.append("Config paths below are relative to the Klipper config directory.")
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
        return self.collect_with_options()

    def collect_with_options(self, *, include_unincluded_configs: bool = False) -> ConfigSnapshot:
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
        if include_unincluded_configs:
            self._collect_unincluded_config_files(visited, documents, section_locations, placeholders, notes)
        if self._max_documents is not None and len(documents) >= self._max_documents:
            notes.append(f"Config collection stopped after {self._max_documents} files to keep context bounded.")

        return ConfigSnapshot(
            root_file=self._relative_path_string(root_file),
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
                notes.append(f"Configured root config file was not found: {self._relative_path_string(root_file)}")
                return None
            if not root_file.is_file():
                notes.append(f"Configured root config path is not a file: {self._relative_path_string(root_file)}")
                return None
            return root_file

        auto_detected = self._auto_detect_root_file()
        if auto_detected is None:
            notes.append(f"No root config file could be auto-detected under: {self._config_dir}")
            return None
        notes.append(f"Auto-detected root config file: {self._relative_path_string(auto_detected)}")
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
            notes.append(f"Could not read config file {self._relative_path_string(path)}: {exc}")
            return

        display_path = self._relative_path_string(path)
        sections = self._extract_sections(raw_content)
        section_locations.extend(self._extract_section_locations(display_path, raw_content))
        placeholders.extend(self._detect_placeholders(display_path, raw_content))
        clipped_content = self._clip_text(raw_content.strip(), self._max_chars_per_document)
        documents.append(
            ConfigDocument(
                path=display_path,
                content=clipped_content,
                sections=sections,
            )
        )

        for pattern in self._extract_include_patterns(raw_content):
            matches = self._resolve_include_matches(path.parent, pattern)
            if not matches:
                notes.append(f"Include pattern matched no files: {pattern} (from {display_path})")
                continue
            for match in matches:
                if self._should_ignore(match):
                    notes.append(
                        f"Ignored config file due to config_context.ignore_globs: {self._relative_path_string(match)}"
                    )
                    continue
                self._collect_file(match, visited, documents, section_locations, placeholders, notes)
                if self._max_documents is not None and len(documents) >= self._max_documents:
                    return

    def _collect_unincluded_config_files(
        self,
        visited: set[Path],
        documents: list[ConfigDocument],
        section_locations: list[ConfigSectionLocation],
        placeholders: list[ConfigPlaceholder],
        notes: list[str],
    ) -> None:
        candidates = [
            path
            for path in sorted(self._config_dir.rglob("*.cfg"), key=lambda candidate: candidate.as_posix().lower())
            if path.is_file() and not self._should_ignore(path)
        ]
        added = 0
        for path in candidates:
            if self._max_documents is not None and len(documents) >= self._max_documents:
                return
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in visited:
                continue

            notes.append(
                "Additional config file collected for lookup context; it may not be active unless included: "
                f"{self._relative_path_string(path)}"
            )
            before_count = len(documents)
            self._collect_file(path, visited, documents, section_locations, placeholders, notes)
            if len(documents) > before_count:
                added += 1

        if added:
            notes.append(f"Collected {added} additional config file(s) outside the active include walk for lookup context.")

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
    def _extract_section_locations(cls, path: str, content: str) -> list[ConfigSectionLocation]:
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
                    path=path,
                    line_number=line_number,
                    section=section,
                )
            )

        return locations

    @classmethod
    def _detect_placeholders(cls, path: str, content: str) -> list[ConfigPlaceholder]:
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
                    path=path,
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
        if _looks_like_edit_request(lowered):
            intent: ConfigRequestIntent = "edit"
        elif _looks_like_explain_request(lowered):
            intent = "explain"
        else:
            intent = "locate"
        return ConfigRequestTarget(
            feature=feature,
            rationale=f"Matched explicit section lookup for [{explicit_section}].",
            intent=intent,
            section_name=explicit_section,
        )

    macro_section = _extract_macro_section_name(message)
    if macro_section and _looks_like_edit_request(lowered):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro edit request for [{macro_section}].",
            intent="edit",
            section_name=macro_section,
        )

    if macro_section and (_looks_like_lookup_request(lowered) or _looks_like_lookup_correction(lowered)):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro lookup for [{macro_section}].",
            intent="locate",
            section_name=macro_section,
        )

    if macro_section and _looks_like_explain_request(lowered):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro explanation request for [{macro_section}].",
            intent="explain",
            section_name=macro_section,
        )

    for feature, keywords in _FEATURE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            if _looks_like_lookup_request(lowered):
                intent = "locate"
            elif _looks_like_edit_request(lowered):
                intent = "edit"
            elif _looks_like_explain_request(lowered):
                intent = "explain"
            else:
                intent = "generate"
            return ConfigRequestTarget(
                feature=feature,
                rationale=f"Matched request keywords for {feature}.",
                intent=intent,
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
        "change",
        "define",
        "disable",
        "edit",
        "enable",
        "improve",
        "modify",
        "optimize",
        "remove",
        "rename",
        "replace",
        "rewrite",
        "turn off",
        "turn on",
        "update",
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
    if _extract_macro_section_name(message) and (
        has_lookup_intent
        or _looks_like_lookup_correction(lowered)
        or _looks_like_explain_request(lowered)
        or _looks_like_edit_request(lowered)
    ):
        return True

    has_feature = any(keyword in lowered for _, keywords in _FEATURE_KEYWORDS for keyword in keywords)
    return has_feature and (has_generate_intent or has_lookup_intent or _looks_like_explain_request(lowered))


def build_config_lookup_response(
    snapshot: ConfigSnapshot,
    target: ConfigRequestTarget,
    *,
    include_content: bool = False,
) -> tuple[str, list[str]]:
    matches = snapshot.find_section_locations(target)
    label = _describe_lookup_target(target)

    if matches:
        if _is_exact_macro_lookup(target):
            return _build_exact_macro_lookup_response(snapshot, target, matches, include_content=include_content)

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


def _looks_like_lookup_correction(lowered_message: str) -> bool:
    return any(word in lowered_message for word in _LOOKUP_CORRECTION_WORDS)


def _looks_like_explain_request(lowered_message: str) -> bool:
    return any(word in lowered_message for word in _EXPLAIN_INTENT_WORDS)


def _looks_like_edit_request(lowered_message: str) -> bool:
    return any(_contains_intent_phrase(lowered_message, word) for word in _EDIT_INTENT_WORDS)


def _contains_intent_phrase(lowered_message: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9_])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9_])"
    return bool(re.search(pattern, lowered_message))


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


def _extract_macro_section_name(message: str) -> str | None:
    macro_word_match = _MACRO_WORD_PATTERN.search(message)
    if macro_word_match:
        before = message[: macro_word_match.start()]
        after = message[macro_word_match.end() :]
        near_macro = _last_macro_candidate(before) or _first_macro_candidate(after)
        if near_macro:
            return near_macro

    for match in _MACRO_IDENTIFIER_PATTERN.finditer(message):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=False)
        if candidate:
            return candidate

    for match in _MACRO_COMMAND_PATTERN.finditer(message):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=False)
        if candidate:
            return candidate

    return None


def _last_macro_candidate(text: str) -> str | None:
    identifier_matches = list(_MACRO_IDENTIFIER_PATTERN.finditer(text))
    for match in reversed(identifier_matches):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=True)
        if candidate:
            return candidate

    words = _macro_words(text)
    candidate_words: list[str] = []
    for word in reversed(words):
        if word.lower() in _MACRO_NAME_BOUNDARY_WORDS:
            break
        candidate_words.append(word)
        if len(candidate_words) == 4:
            break

    if not candidate_words:
        return None
    candidate_words.reverse()
    return _normalize_macro_name_candidate(" ".join(candidate_words), allow_plain=True)


def _first_macro_candidate(text: str) -> str | None:
    identifier_match = _MACRO_IDENTIFIER_PATTERN.search(text)
    if identifier_match:
        candidate = _normalize_macro_name_candidate(identifier_match.group(0), allow_plain=True)
        if candidate:
            return candidate

    words = _macro_words(text)
    while words and words[0].lower() in _MACRO_NAME_LEADING_WORDS:
        words.pop(0)

    candidate_words: list[str] = []
    for word in words:
        if word.lower() in _MACRO_NAME_BOUNDARY_WORDS:
            break
        candidate_words.append(word)
        if len(candidate_words) == 4:
            break

    if not candidate_words:
        return None
    return _normalize_macro_name_candidate(" ".join(candidate_words), allow_plain=True)


def _macro_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)


def _normalize_macro_name_candidate(raw_name: str, *, allow_plain: bool) -> str | None:
    words = _macro_words(raw_name.replace("`", " "))
    while words and words[0].lower() in _MACRO_NAME_LEADING_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _MACRO_NAME_BOUNDARY_WORDS:
        words.pop()

    if not words or len(words) > 4:
        return None

    if any(word.lower() in _MACRO_NAME_BOUNDARY_WORDS for word in words):
        return None

    if len(words) == 1 and not allow_plain and not _looks_like_macro_name_token(words[0]):
        return None

    macro_name = "_".join(word.replace("-", "_") for word in words).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", macro_name):
        return None
    return f"gcode_macro {macro_name}"


def _looks_like_macro_name_token(token: str) -> bool:
    return "_" in token or "-" in token or token.isupper()


def _normalize_section_lookup_key(section_name: str) -> str:
    return re.sub(r"[\s-]+", "_", section_name.strip().lower())


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


def _is_exact_macro_lookup(target: ConfigRequestTarget) -> bool:
    return bool(target.section_name and _section_matches_prefix(target.section_name, "gcode_macro"))


def _build_exact_macro_lookup_response(
    snapshot: ConfigSnapshot,
    target: ConfigRequestTarget,
    matches: list[ConfigSectionLocation],
    *,
    include_content: bool,
) -> tuple[str, list[str]]:
    if len(matches) == 1:
        match = matches[0]
        macro_name = _macro_name_from_section(match.section) or _macro_name_from_section(target.section_name or "")
        subject = macro_name or f"[{match.section}]"
        lines = [f"{subject} is defined in {match.path}:{match.line_number} as [{match.section}]."]
        if macro_name:
            references = _find_macro_references(snapshot, macro_name, definition=match)
            lines.extend(["", *_format_macro_reference_lines(macro_name, references)])

        block = snapshot.section_block(match)
        behavior_lines = _format_macro_behavior_lines(block)
        if behavior_lines:
            lines.extend(["", *behavior_lines])

        if include_content:
            if block:
                lines.extend(["", "Config:", "```ini", block, "```"])
        return "\n".join(lines), []

    lines = [
        f"I found {len(matches)} active definitions for {_describe_lookup_target(target)} in the current config tree.",
        "",
        "Matches:",
    ]
    lines.extend(f"- {match.summary()}" for match in matches)
    return "\n".join(lines), ["Remove or rename duplicate macro definitions so only one active section remains."]


def _macro_name_from_section(section_name: str) -> str | None:
    parts = section_name.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "gcode_macro":
        return None
    return parts[1].strip() or None


def _find_macro_references(
    snapshot: ConfigSnapshot,
    macro_name: str,
    *,
    definition: ConfigSectionLocation,
    limit: int = 8,
) -> list[_ConfigLineReference]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(macro_name)}(?![A-Za-z0-9_-])", re.IGNORECASE)
    references: list[_ConfigLineReference] = []

    for document in snapshot.documents:
        current_section: str | None = None
        for line_number, raw_line in enumerate(document.content.splitlines(), start=1):
            section_match = _SECTION_LINE_PATTERN.match(raw_line)
            if section_match:
                current_section = raw_line.strip()[1:-1].strip()
                continue

            if document.path == definition.path and current_section == definition.section:
                continue

            searchable_line = _strip_config_comments(raw_line).strip()
            if not searchable_line or not pattern.search(searchable_line):
                continue

            references.append(
                _ConfigLineReference(
                    path=document.path,
                    line_number=line_number,
                    section=current_section,
                    line_text=searchable_line,
                )
            )
            if len(references) >= limit:
                return references

    return references


def _format_macro_reference_lines(macro_name: str, references: list[_ConfigLineReference]) -> list[str]:
    if not references:
        return [
            "Used by: no direct calls found in the collected config files.",
            "It may still be run manually, from the printer UI, or by slicer/start g-code outside this config tree.",
        ]

    lines = ["Used by:"]
    lines.extend(f"- {reference.summary()}" for reference in references)
    return lines


def _format_macro_behavior_lines(block: str | None) -> list[str]:
    if not block:
        return []

    description, commands = _extract_macro_behavior(block)
    lines: list[str] = []
    if description:
        lines.append(f"Description: {description}")

    summaries = [_summarize_macro_command(command) for command in commands[:5]]
    if not summaries:
        return lines

    lines.append("What it does:")
    lines.extend(f"- {summary}" for summary in summaries)
    if len(commands) > len(summaries):
        lines.append(f"- ...and {len(commands) - len(summaries)} more command(s).")
    return lines


def _extract_macro_behavior(block: str) -> tuple[str | None, list[str]]:
    description: str | None = None
    commands: list[str] = []
    in_gcode = False

    for raw_line in block.splitlines()[1:]:
        line_without_comment = _strip_config_comments(raw_line).rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue

        option_match = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$", line_without_comment)
        if option_match:
            option = option_match.group(1).strip().lower()
            value = option_match.group(2).strip()
            in_gcode = option == "gcode"
            if option == "description" and value:
                description = value.strip("\"'")
            elif in_gcode and value:
                commands.append(value)
            continue

        if not in_gcode:
            continue

        if stripped.startswith(("{%", "{#", "{{")):
            continue
        commands.append(stripped)

    return description, commands


def _summarize_macro_command(command: str) -> str:
    compact_command = re.sub(r"\s+", " ", command).strip()
    command_name = compact_command.split(maxsplit=1)[0].upper() if compact_command else ""
    params = _parse_gcode_params(compact_command)

    if command_name == "SET_FILAMENT_SENSOR":
        sensor = params.get("SENSOR")
        enabled = params.get("ENABLE")
        if sensor and enabled == "1":
            return f"enables filament sensor `{_inline_code(sensor)}`."
        if sensor and enabled == "0":
            return f"disables filament sensor `{_inline_code(sensor)}`."
        if sensor:
            return f"updates filament sensor `{_inline_code(sensor)}`."

    return f"runs `{_inline_code(compact_command)}`."


def _parse_gcode_params(command: str) -> dict[str, str]:
    return {
        match.group(1).upper(): match.group(2).strip("\"'")
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)", command)
    }


def _strip_config_comments(line: str) -> str:
    return line.split("#", 1)[0].split(";", 1)[0]


def _inline_code(value: str) -> str:
    return value.replace("`", "'")


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
