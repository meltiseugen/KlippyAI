from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from klippyai_agent.schemas import ArtifactInput, ArtifactKind


@dataclass(frozen=True, slots=True)
class LogFamily:
    kind: ArtifactKind
    active_name: str
    display_name: str
    startup_markers: tuple[re.Pattern[str], ...]


class HostLogCollector:
    _FAMILIES: tuple[LogFamily, ...] = (
        LogFamily(
            kind="klippy_log",
            active_name="klippy.log",
            display_name="Klippy",
            startup_markers=(
                re.compile(r"^Start printer at ", re.MULTILINE),
                re.compile(r"^=============== Log rollover at ", re.MULTILINE),
                re.compile(r"^Git version: ", re.MULTILINE),
            ),
        ),
        LogFamily(
            kind="moonraker_log",
            active_name="moonraker.log",
            display_name="Moonraker",
            startup_markers=(
                re.compile(r"^.*Starting Moonraker", re.MULTILINE),
                re.compile(r"^=============== Log rollover at ", re.MULTILINE),
                re.compile(r"^Moonraker version: ", re.MULTILINE),
            ),
        ),
        LogFamily(
            kind="system_log",
            active_name="klippyai.log",
            display_name="KlippyAI",
            startup_markers=(
                re.compile(r"^.*Starting KlippyAI", re.MULTILINE),
                re.compile(r"^.*Application startup complete\.", re.MULTILINE),
            ),
        ),
    )

    def __init__(
        self,
        printer_data_root: Path,
        *,
        logs_dir_name: str = "logs",
        max_files_per_family: int = 3,
        active_tail_bytes: int = 160_000,
        rotated_tail_bytes: int = 80_000,
        artifact_char_limit: int = 18_000,
    ) -> None:
        self._logs_dir = printer_data_root / logs_dir_name
        self._max_files_per_family = max_files_per_family
        self._active_tail_bytes = active_tail_bytes
        self._rotated_tail_bytes = rotated_tail_bytes
        self._artifact_char_limit = artifact_char_limit

    def collect(self) -> tuple[list[ArtifactInput], list[str]]:
        artifacts: list[ArtifactInput] = []
        notes: list[str] = []

        if not self._logs_dir.exists():
            notes.append(f"Host log directory does not exist: {self._logs_dir}")
            return artifacts, notes

        if not self._logs_dir.is_dir():
            notes.append(f"Host log path is not a directory: {self._logs_dir}")
            return artifacts, notes

        for family in self._FAMILIES:
            family_files = self._discover_family_files(family)
            if not family_files:
                continue

            notes.append(
                f"Loaded {len(family_files)} {family.display_name} log file(s) from {self._logs_dir}."
            )

            for path in family_files:
                artifact = self._build_artifact(path, family)
                if artifact is not None:
                    artifacts.append(artifact)

        if not artifacts:
            notes.append(f"No supported host log files were found in {self._logs_dir}.")

        return artifacts, notes

    def _discover_family_files(self, family: LogFamily) -> list[Path]:
        candidates: list[Path] = []

        for path in self._logs_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix == ".gz":
                continue
            if self._matches_family(path.name, family.active_name):
                candidates.append(path)

        candidates.sort(
            key=lambda path: (
                1 if path.name == family.active_name else 0,
                path.stat().st_mtime,
                path.name,
            ),
            reverse=True,
        )
        return candidates[: self._max_files_per_family]

    @staticmethod
    def _matches_family(filename: str, active_name: str) -> bool:
        return (
            filename == active_name
            or filename.startswith(f"{active_name}.")
            or filename.startswith(f"{active_name}-")
        )

    def _build_artifact(self, path: Path, family: LogFamily) -> ArtifactInput | None:
        is_active = path.name == family.active_name
        byte_limit = self._active_tail_bytes if is_active else self._rotated_tail_bytes
        excerpt, truncated = self._read_tail(path, byte_limit)
        if not excerpt.strip():
            return None

        excerpt, focused = self._focus_recent_session(excerpt, family)
        excerpt = self._clip_text(excerpt, self._artifact_char_limit)
        metadata = self._render_metadata(path, family, is_active, byte_limit, truncated, focused)
        content = f"{metadata}\n\n{excerpt}".strip()

        return ArtifactInput(
            kind=family.kind,
            label=self._label_for(path, is_active),
            content=self._clip_text(content, 39_000),
        )

    @staticmethod
    def _read_tail(path: Path, byte_limit: int) -> tuple[str, bool]:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            offset = max(file_size - byte_limit, 0)
            handle.seek(offset)
            data = handle.read()

        truncated = offset > 0
        if truncated:
            newline_index = data.find(b"\n")
            if newline_index >= 0:
                data = data[newline_index + 1 :]

        return data.decode("utf-8", errors="replace").strip(), truncated

    @staticmethod
    def _focus_recent_session(text: str, family: LogFamily) -> tuple[str, bool]:
        last_marker_index = -1
        for pattern in family.startup_markers:
            for match in pattern.finditer(text):
                last_marker_index = max(last_marker_index, match.start())

        if last_marker_index <= 0:
            return text, False

        focused = text[last_marker_index:].strip()
        if not focused:
            return text, False
        return focused, True

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text

        head = max((limit - 32) // 2, 0)
        tail = max(limit - head - 17, 0)
        return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"

    @staticmethod
    def _label_for(path: Path, is_active: bool) -> str:
        suffix = "current" if is_active else "archive"
        return f"{path.name} ({suffix})"

    @staticmethod
    def _render_metadata(
        path: Path,
        family: LogFamily,
        is_active: bool,
        byte_limit: int,
        truncated: bool,
        focused: bool,
    ) -> str:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        lines = [
            f"Host log: {family.display_name}",
            f"Path: {path}",
            f"File size: {stat.st_size} bytes",
            f"Modified: {mtime}",
            f"Selection: last {min(stat.st_size, byte_limit)} bytes from the {'active' if is_active else 'archived'} log file",
        ]
        if truncated:
            lines.append("Tail mode: file excerpted from the end to keep context bounded.")
        if focused:
            lines.append("Focus mode: narrowed to the latest startup or rollover block inside the excerpt.")
        return "\n".join(lines)
