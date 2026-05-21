from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from klippyai_agent.schemas import ArtifactInput, ArtifactKind


@dataclass(frozen=True, slots=True)
class KnownLogKind:
    kind: ArtifactKind
    display_name: str


class HostLogCollector:
    _KNOWN_LOGS: dict[str, KnownLogKind] = {
        "klippy.log": KnownLogKind(kind="klippy_log", display_name="Klippy"),
        "moonraker.log": KnownLogKind(kind="moonraker_log", display_name="Moonraker"),
        "klippyai.log": KnownLogKind(kind="system_log", display_name="KlippyAI"),
    }

    def __init__(
        self,
        printer_data_root: Path,
        *,
        logs_dir_name: str = "logs",
        default_tail_lines: int = 100,
        tail_lines_by_log: dict[str, int] | None = None,
        excluded_logs: list[str] | tuple[str, ...] | set[str] | None = None,
        artifact_char_limit: int = 18_000,
    ) -> None:
        self._logs_dir = printer_data_root / logs_dir_name
        self._default_tail_lines = default_tail_lines
        self._tail_lines_by_log = {
            str(key).strip().lower(): int(value)
            for key, value in (tail_lines_by_log or {}).items()
            if str(key).strip() and int(value) > 0
        }
        self._excluded_logs = {str(item).strip().lower() for item in (excluded_logs or ()) if str(item).strip()}
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

        log_files = self._discover_log_files()
        if not log_files:
            notes.append(f"No current .log files were found in {self._logs_dir}.")
            return artifacts, notes

        notes.append(f"Loaded {len(log_files)} current log file(s) from {self._logs_dir}.")

        for path in log_files:
            artifact = self._build_artifact(path)
            if artifact is not None:
                artifacts.append(artifact)

        return artifacts, notes

    def _discover_log_files(self) -> list[Path]:
        candidates = [
            path
            for path in self._logs_dir.iterdir()
            if path.is_file()
            and not path.name.endswith(".gz")
            and path.name.lower().endswith(".log")
            and not self._is_excluded(path)
        ]
        candidates.sort(key=lambda path: (path.stat().st_mtime, path.name.lower()), reverse=True)
        return candidates

    def _build_artifact(self, path: Path) -> ArtifactInput | None:
        tail_lines = self._tail_lines_for(path)
        excerpt, truncated = self._read_last_lines(path, tail_lines)
        if not excerpt.strip():
            return None

        known_kind = self._KNOWN_LOGS.get(path.name)
        kind = known_kind.kind if known_kind else "system_log"
        display_name = known_kind.display_name if known_kind else path.name
        metadata = self._render_metadata(path, display_name, tail_lines, truncated)
        content = self._clip_text(f"{metadata}\n\n{excerpt}".strip(), self._artifact_char_limit)

        return ArtifactInput(
            kind=kind,
            label=path.name,
            content=content,
        )

    def _tail_lines_for(self, path: Path) -> int:
        log_key = path.stem.strip().lower()
        return self._tail_lines_by_log.get(log_key, self._default_tail_lines)

    def _is_excluded(self, path: Path) -> bool:
        if not self._excluded_logs:
            return False

        file_name = path.name.strip().lower()
        file_stem = path.stem.strip().lower()
        for item in self._excluded_logs:
            if item == file_name or item == file_stem:
                return True
            if any(token in item for token in "*?[]"):
                if fnmatch(file_name, item) or fnmatch(file_stem, item):
                    return True
        return False

    @staticmethod
    def _read_last_lines(path: Path, max_lines: int) -> tuple[str, bool]:
        if max_lines <= 0:
            return "", False

        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            block_size = 8192
            remaining = file_size
            data = b""

            while remaining > 0 and data.count(b"\n") <= max_lines:
                read_size = min(block_size, remaining)
                remaining -= read_size
                handle.seek(remaining)
                data = handle.read(read_size) + data

        lines = data.decode("utf-8", errors="replace").splitlines()
        truncated = len(lines) > max_lines or remaining > 0
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines).strip(), truncated

    def _render_metadata(self, path: Path, display_name: str, tail_lines: int, truncated: bool) -> str:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        lines = [
            f"Host log: {display_name}",
            f"Path: {path}",
            f"File size: {stat.st_size} bytes",
            f"Modified: {mtime}",
            f"Selection: last {tail_lines} line(s) from the current log file",
        ]
        if truncated:
            lines.append("Tail mode: file excerpted from the end to keep context bounded.")
        return "\n".join(lines)

    def _clip_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text

        head = max((limit - 32) // 2, 0)
        tail = max(limit - head - 17, 0)
        return f"{text[:head]}\n...[truncated]...\n{text[-tail:]}"
