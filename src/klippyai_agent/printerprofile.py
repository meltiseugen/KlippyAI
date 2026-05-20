from __future__ import annotations

import asyncio
import configparser
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from klippyai_agent.moonraker import MoonrakerClient, MoonrakerError
from klippyai_agent.printerconfig import ConfigCollector, ConfigDocument, ConfigSnapshot
from klippyai_agent.settings import Settings

ProfileConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class ProfileEvidence:
    summary: str
    source: str
    confidence: ProfileConfidence = "medium"


@dataclass(frozen=True, slots=True)
class DetectedAddon:
    name: str
    source: str
    confidence: ProfileConfidence = "medium"
    detail: str | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "confidence": self.confidence,
            "detail": self.detail,
        }


@dataclass(slots=True)
class PrinterProfile:
    firmware_flavor: str | None = None
    firmware_version: str | None = None
    klipper_repo_origin: str | None = None
    klipper_path: str | None = None
    printer_state: str | None = None
    state_message: str | None = None
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
    services: list[str] = field(default_factory=list)
    canbus_interfaces: list[str] = field(default_factory=list)
    mcu_names: list[str] = field(default_factory=list)
    object_names: list[str] = field(default_factory=list)
    addons: list[DetectedAddon] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence: list[ProfileEvidence] = field(default_factory=list)

    @property
    def canbus_enabled(self) -> bool:
        return bool(self.canbus_interfaces or self._has_can_mcu())

    def _has_can_mcu(self) -> bool:
        return any(
            lowered != "mcu" and ("toolhead" in lowered or "can" in lowered)
            for lowered in (name.lower() for name in self.mcu_names)
        )

    def summary_label(self) -> str:
        parts: list[str] = []
        if self.firmware_flavor:
            if self.firmware_version:
                parts.append(f"{self.firmware_flavor} {self.firmware_version}")
            else:
                parts.append(self.firmware_flavor)
        if self.toolhead_board:
            parts.append(self.toolhead_board)
        elif self.mainboard:
            parts.append(self.mainboard)
        if self.canbus_enabled:
            parts.append("CAN")
        if self.addons:
            addon_names = ", ".join(addon.name for addon in self.addons[:2])
            parts.append(addon_names)
        return " | ".join(parts[:4])

    def to_prompt_block(self) -> str:
        lines: list[str] = []
        if self.summary_label():
            lines.append(f"Profile summary: {self.summary_label()}")
        if self.printer_state:
            lines.append(f"Printer state: {self.printer_state}")
        if self.state_message:
            lines.append(f"Printer state message: {self.state_message}")
        if self.host_model:
            lines.append(f"Host model: {self.host_model}")
        if self.host_distribution:
            lines.append(f"Host distribution: {self.host_distribution}")
        if self.mainboard:
            lines.append(f"Mainboard: {self.mainboard}")
        if self.mainboard_mcu:
            lines.append(f"Mainboard MCU: {self.mainboard_mcu}")
        if self.toolhead:
            lines.append(f"Toolhead: {self.toolhead}")
        if self.toolhead_board:
            lines.append(f"Toolhead board: {self.toolhead_board}")
        if self.probe_type:
            lines.append(f"Probe type: {self.probe_type}")
        if self.accelerometer:
            lines.append(f"Accelerometer: {self.accelerometer}")
        if self.filament_sensor:
            lines.append(f"Filament sensor: {self.filament_sensor}")
        if self.camera_stack:
            lines.append(f"Camera stack: {self.camera_stack}")
        lines.append(f"Bed mesh configured: {'yes' if self.bed_mesh_configured else 'no'}")
        lines.append(f"Input shaper configured: {'yes' if self.input_shaper_configured else 'no'}")
        if self.mcu_names:
            lines.append(f"MCUs: {', '.join(self.mcu_names[:8])}")
        if self.canbus_interfaces:
            lines.append(f"CAN interfaces: {', '.join(self.canbus_interfaces[:4])}")
        if self.addons:
            addon_lines = []
            for addon in self.addons[:8]:
                detail = f" ({addon.detail})" if addon.detail else ""
                addon_lines.append(f"- {addon.name} [{addon.confidence}] via {addon.source}{detail}")
            lines.append("Detected addons:\n" + "\n".join(addon_lines))
        if self.notes:
            lines.append("Profile notes:\n" + "\n".join(f"- {note}" for note in self.notes[:8]))
        return "\n".join(lines) if lines else "No printer profile could be detected."

    def to_state(self) -> dict[str, Any]:
        return {
            "firmware_flavor": self.firmware_flavor,
            "firmware_version": self.firmware_version,
            "klipper_repo_origin": self.klipper_repo_origin,
            "klipper_path": self.klipper_path,
            "printer_state": self.printer_state,
            "state_message": self.state_message,
            "host_model": self.host_model,
            "host_distribution": self.host_distribution,
            "mainboard": self.mainboard,
            "mainboard_mcu": self.mainboard_mcu,
            "toolhead": self.toolhead,
            "toolhead_board": self.toolhead_board,
            "probe_type": self.probe_type,
            "accelerometer": self.accelerometer,
            "filament_sensor": self.filament_sensor,
            "camera_stack": self.camera_stack,
            "bed_mesh_configured": self.bed_mesh_configured,
            "input_shaper_configured": self.input_shaper_configured,
            "services": list(self.services),
            "canbus_interfaces": list(self.canbus_interfaces),
            "mcu_names": list(self.mcu_names),
            "object_names": list(self.object_names),
            "addons": [addon.to_state() for addon in self.addons],
            "notes": list(self.notes),
            "evidence": [
                {
                    "summary": item.summary,
                    "source": item.source,
                    "confidence": item.confidence,
                }
                for item in self.evidence
            ],
        }

    def to_summary(self) -> dict[str, Any]:
        return {
            "firmware_flavor": self.firmware_flavor,
            "firmware_version": self.firmware_version,
            "host_model": self.host_model,
            "host_distribution": self.host_distribution,
            "mainboard": self.mainboard,
            "mainboard_mcu": self.mainboard_mcu,
            "toolhead": self.toolhead,
            "toolhead_board": self.toolhead_board,
            "probe_type": self.probe_type,
            "accelerometer": self.accelerometer,
            "filament_sensor": self.filament_sensor,
            "camera_stack": self.camera_stack,
            "bed_mesh_configured": self.bed_mesh_configured,
            "input_shaper_configured": self.input_shaper_configured,
            "printer_state": self.printer_state,
            "canbus_enabled": self.canbus_enabled,
            "addons": [addon.to_state() for addon in self.addons],
            "summary": self.summary_label(),
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> PrinterProfile:
        addons = [
            DetectedAddon(
                name=str(item.get("name", "")),
                source=str(item.get("source", "unknown")),
                confidence=str(item.get("confidence", "medium")),
                detail=str(item.get("detail")) if item.get("detail") is not None else None,
            )
            for item in data.get("addons", [])
        ]
        evidence = [
            ProfileEvidence(
                summary=str(item.get("summary", "")),
                source=str(item.get("source", "unknown")),
                confidence=str(item.get("confidence", "medium")),
            )
            for item in data.get("evidence", [])
        ]
        return cls(
            firmware_flavor=str(data.get("firmware_flavor")) if data.get("firmware_flavor") else None,
            firmware_version=str(data.get("firmware_version")) if data.get("firmware_version") else None,
            klipper_repo_origin=str(data.get("klipper_repo_origin")) if data.get("klipper_repo_origin") else None,
            klipper_path=str(data.get("klipper_path")) if data.get("klipper_path") else None,
            printer_state=str(data.get("printer_state")) if data.get("printer_state") else None,
            state_message=str(data.get("state_message")) if data.get("state_message") else None,
            host_model=str(data.get("host_model")) if data.get("host_model") else None,
            host_distribution=str(data.get("host_distribution")) if data.get("host_distribution") else None,
            mainboard=str(data.get("mainboard")) if data.get("mainboard") else None,
            mainboard_mcu=str(data.get("mainboard_mcu")) if data.get("mainboard_mcu") else None,
            toolhead=str(data.get("toolhead")) if data.get("toolhead") else None,
            toolhead_board=str(data.get("toolhead_board")) if data.get("toolhead_board") else None,
            probe_type=str(data.get("probe_type")) if data.get("probe_type") else None,
            accelerometer=str(data.get("accelerometer")) if data.get("accelerometer") else None,
            filament_sensor=str(data.get("filament_sensor")) if data.get("filament_sensor") else None,
            camera_stack=str(data.get("camera_stack")) if data.get("camera_stack") else None,
            bed_mesh_configured=_as_bool(data.get("bed_mesh_configured")),
            input_shaper_configured=_as_bool(data.get("input_shaper_configured")),
            services=[str(item) for item in data.get("services", [])],
            canbus_interfaces=[str(item) for item in data.get("canbus_interfaces", [])],
            mcu_names=[str(item) for item in data.get("mcu_names", [])],
            object_names=[str(item) for item in data.get("object_names", [])],
            addons=addons,
            notes=[str(item) for item in data.get("notes", [])],
            evidence=evidence,
        )


def build_profile_from_settings(settings: Settings) -> PrinterProfile:
    addon_names = _split_addon_names(settings.addons)
    return PrinterProfile(
        firmware_flavor=settings.firmware_flavor,
        firmware_version=settings.firmware_version,
        host_model=settings.host_model,
        host_distribution=settings.host_distribution,
        mainboard=settings.mainboard,
        mainboard_mcu=settings.mainboard_mcu,
        toolhead=settings.toolhead,
        toolhead_board=settings.toolhead_board,
        probe_type=settings.probe_type,
        accelerometer=settings.accelerometer,
        filament_sensor=settings.filament_sensor,
        camera_stack=settings.camera_stack,
        bed_mesh_configured=settings.bed_mesh_configured,
        input_shaper_configured=settings.input_shaper_configured,
        addons=[
            DetectedAddon(
                name=name,
                source="klippyai.cfg",
                confidence="high",
            )
            for name in addon_names
        ],
        evidence=[
            ProfileEvidence("Printer profile loaded from klippyai.cfg.", "klippyai.cfg", "high"),
        ],
        notes=[
            "Static printer profile loaded from klippyai.cfg.",
        ],
        canbus_interfaces=["configured"] if settings.canbus_enabled else [],
    )


def write_profile_to_cfg(
    config_file: Path,
    profile: PrinterProfile,
    *,
    root_config_file: str | None = None,
    overwrite: bool = False,
) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_file, encoding="utf-8")

    section_values = {
        "printer_identity": {
            "firmware_flavor": profile.firmware_flavor or "",
            "firmware_version": profile.firmware_version or "",
            "host_model": profile.host_model or "",
            "host_distribution": profile.host_distribution or "",
            "mainboard": profile.mainboard or "",
            "mainboard_mcu": profile.mainboard_mcu or "",
            "toolhead": profile.toolhead or "",
            "toolhead_board": profile.toolhead_board or "",
        },
        "printer_capabilities": {
            "probe_type": profile.probe_type or "",
            "accelerometer": profile.accelerometer or "",
            "filament_sensor": profile.filament_sensor or "",
            "camera_stack": profile.camera_stack or "",
            "bed_mesh_configured": "true" if profile.bed_mesh_configured else "false",
            "input_shaper_configured": "true" if profile.input_shaper_configured else "false",
            "canbus_enabled": "true" if profile.canbus_enabled else "false",
            "addons": ", ".join(addon.name for addon in profile.addons),
        },
        "config_context": {
            "root_config_file": root_config_file or "",
        },
    }

    parser.remove_section("printer_geometry")

    for section, values in section_values.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            if overwrite:
                parser.set(section, key, value)
                continue
            existing = parser.get(section, key, fallback="").strip()
            if existing:
                continue
            parser.set(section, key, value)

    with config_file.open("w", encoding="utf-8") as handle:
        parser.write(handle)


def _split_addon_names(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [item.strip() for item in re.split(r"[,\n;]+", value) if item.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(part)
    return ordered


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class PrinterProfileCollector:
    _SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    _OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$")
    _BOARD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("BTT Octopus Pro", ("octopus pro",)),
        ("BTT Octopus", ("octopus",)),
        ("BTT Manta M8P", ("manta m8p",)),
        ("BTT Manta M5P", ("manta m5p",)),
        ("BTT SKR Mini E3", ("skr mini e3",)),
        ("BTT SKR Pico", ("skr pico",)),
        ("BTT SKR 3", ("skr 3",)),
        ("BTT Spider", ("spider",)),
        ("BTT EBB36", ("ebb36",)),
        ("BTT EBB42", ("ebb42",)),
        ("Mellow SB2209", ("sb2209",)),
        ("Mellow SB2240", ("sb2240",)),
        ("Mellow Fly", ("mellow fly", "fly-", "fly ")),
        ("Fysetc Spider", ("fysetc spider",)),
    )
    _TOOLHEAD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Stealthburner", ("stealthburner",)),
        ("Afterburner", ("afterburner",)),
        ("Dragon Burner", ("dragonburner", "dragon burner")),
        ("Orbiter", ("orbiter",)),
        ("Hermit Crab", ("hermitcrab", "hermit crab")),
        ("EVA", ("eva toolhead", "eva-")),
    )
    _ADDON_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Beacon", ("beacon",)),
        ("Eddy", ("probe_eddy_current", "eddy")),
        ("Cartographer", ("cartographer",)),
        ("Klicky", ("klicky", "dockable_probe")),
        ("KAMP", ("klipper-adaptive-meshing-purging", "adaptive_mesh", "line_purge", "smart_park")),
        ("OctoEverywhere", ("octoeverywhere",)),
        ("Crowsnest", ("crowsnest",)),
        ("Sonar", ("sonar",)),
        ("Moonraker Timelapse", ("moonraker-timelapse", "timelapse")),
        ("KlipperScreen", ("klipperscreen",)),
    )

    def __init__(
        self,
        moonraker: MoonrakerClient,
        config_collector: ConfigCollector,
        *,
        git_timeout_seconds: float = 4.0,
        mainboard_override: str | None = None,
        toolhead_override: str | None = None,
    ) -> None:
        self._moonraker = moonraker
        self._config_collector = config_collector
        self._git_timeout_seconds = git_timeout_seconds
        self._mainboard_override = self._normalize_override(mainboard_override)
        self._toolhead_override = self._normalize_override(toolhead_override)

    async def collect(self, config_snapshot: ConfigSnapshot | None = None) -> PrinterProfile:
        notes: list[str] = []
        evidence: list[ProfileEvidence] = []
        snapshot = config_snapshot or self._config_collector.collect()

        _server_info, printer_info, object_names, system_info, update_status, serial_devices, usb_devices = await asyncio.gather(
            self._collect_optional("server info", self._moonraker.get_server_info, notes),
            self._collect_optional("printer info", self._moonraker.get_printer_info, notes),
            self._collect_optional("printer objects", self._moonraker.list_printer_objects, notes),
            self._collect_optional("system info", self._moonraker.get_system_info, notes),
            self._collect_optional("update status", self._moonraker.get_update_status, notes),
            self._collect_optional("serial devices", self._moonraker.list_serial_devices, notes),
            self._collect_optional("usb devices", self._moonraker.list_usb_devices, notes),
        )

        object_names_list = sorted(str(item) for item in object_names or [])
        parsed_config = self._parse_documents(snapshot.documents)

        klipper_version_info = self._extract_klipper_version_info(update_status)
        firmware_version = self._first_non_empty(
            self._string(klipper_version_info.get("version")),
            self._string(printer_info.get("software_version")) if isinstance(printer_info, dict) else None,
        )
        klipper_path = self._string(printer_info.get("klipper_path")) if isinstance(printer_info, dict) else None
        repo_origin = self._first_non_empty(
            self._string(klipper_version_info.get("remote_url")),
            await asyncio.to_thread(self._detect_git_remote, klipper_path) if klipper_path else None,
        )
        firmware_flavor = self._detect_firmware_flavor(klipper_version_info, repo_origin)
        if firmware_flavor:
            source = "Moonraker update status" if klipper_version_info else "Klipper git remote"
            evidence.append(ProfileEvidence(f"Firmware flavor detected as {firmware_flavor}.", source, "high"))

        host_model = self._detect_host_model(system_info)
        host_distribution = self._detect_distribution(system_info)
        services = self._extract_services(system_info)
        canbus_interfaces = self._extract_canbus_interfaces(system_info)

        mcu_sections = self._extract_mcu_sections(parsed_config)
        mcu_names = [section["name"] for section in mcu_sections]
        primary_mcu = self._select_primary_mcu(mcu_sections)
        toolhead_mcu = self._select_toolhead_mcu(mcu_sections)
        mainboard_mcu = self._describe_mcu(primary_mcu, serial_devices or [], usb_devices or [])
        toolhead_board = self._detect_toolhead_board(toolhead_mcu, serial_devices or [], usb_devices or [], snapshot)
        mainboard = self._detect_mainboard(snapshot, primary_mcu)
        toolhead = self._detect_toolhead(snapshot, toolhead_mcu)
        if self._mainboard_override:
            mainboard = self._mainboard_override
            evidence.append(ProfileEvidence(f"Mainboard declared as {mainboard}.", "klippyai.cfg", "high"))
        if self._toolhead_override:
            toolhead = self._toolhead_override
            evidence.append(ProfileEvidence(f"Toolhead declared as {toolhead}.", "klippyai.cfg", "high"))

        addons = self._detect_addons(snapshot, object_names_list, update_status, services)
        probe_type = self._detect_probe_type(snapshot, object_names_list)
        accelerometer = self._detect_accelerometer(snapshot, object_names_list)
        filament_sensor = self._detect_filament_sensor(snapshot)
        bed_mesh_configured = self._is_bed_mesh_configured(snapshot, object_names_list)
        input_shaper_configured = self._is_input_shaper_configured(snapshot, object_names_list)
        camera_stack = self._detect_camera_stack(addons, services)
        printer_state = self._string(printer_info.get("state")) if isinstance(printer_info, dict) else None
        state_message = self._string(printer_info.get("state_message")) if isinstance(printer_info, dict) else None

        if toolhead_mcu and toolhead_board and "toolhead" in str(toolhead_mcu.get("name", "")).lower():
            evidence.append(ProfileEvidence(f"Detected toolhead board {toolhead_board}.", "Klipper MCU config", "medium"))
        if mainboard_mcu:
            evidence.append(ProfileEvidence(f"Detected mainboard MCU {mainboard_mcu}.", "Moonraker peripherals", "medium"))
        if canbus_interfaces:
            evidence.append(ProfileEvidence("CAN bus interfaces detected on host.", "Moonraker system info", "high"))
        if probe_type:
            evidence.append(ProfileEvidence(f"Probe type detected as {probe_type}.", "Klipper config", "high" if probe_type != "generic" else "medium"))
        if accelerometer and accelerometer != "none":
            evidence.append(ProfileEvidence(f"Accelerometer detected as {accelerometer}.", "Klipper config", "high"))
        if filament_sensor:
            evidence.append(ProfileEvidence(f"Filament sensor detected as {filament_sensor}.", "Klipper config", "high" if filament_sensor != "none" else "medium"))
        if bed_mesh_configured:
            evidence.append(ProfileEvidence("Bed mesh is configured.", "Klipper config", "high"))
        if input_shaper_configured:
            evidence.append(ProfileEvidence("Input shaper is configured.", "Klipper config", "high"))
        if camera_stack and camera_stack != "none":
            evidence.append(ProfileEvidence(f"Camera stack detected as {camera_stack}.", "Moonraker monitored services", "high"))
        if addons:
            for addon in addons[:6]:
                evidence.append(ProfileEvidence(f"Detected addon {addon.name}.", addon.source, addon.confidence))

        return PrinterProfile(
            firmware_flavor=firmware_flavor,
            firmware_version=firmware_version,
            klipper_repo_origin=repo_origin,
            klipper_path=klipper_path,
            printer_state=printer_state,
            state_message=state_message,
            host_model=host_model,
            host_distribution=host_distribution,
            mainboard=mainboard,
            mainboard_mcu=mainboard_mcu,
            toolhead=toolhead,
            toolhead_board=toolhead_board,
            probe_type=probe_type,
            accelerometer=accelerometer,
            filament_sensor=filament_sensor,
            camera_stack=camera_stack,
            bed_mesh_configured=bed_mesh_configured,
            input_shaper_configured=input_shaper_configured,
            services=services,
            canbus_interfaces=canbus_interfaces,
            mcu_names=mcu_names,
            object_names=object_names_list,
            addons=addons,
            notes=notes,
            evidence=evidence,
        )

    async def _collect_optional(
        self,
        label: str,
        func: Any,
        notes: list[str],
    ) -> Any:
        try:
            return await func()
        except MoonrakerError as exc:
            notes.append(f"Could not collect {label}: {exc}")
            return None

    @staticmethod
    def _normalize_override(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _string(value: Any) -> str | None:
        if value is None:
            return None
        stringified = str(value).strip()
        return stringified or None

    @staticmethod
    def _first_non_empty(*values: str | None) -> str | None:
        for value in values:
            if value:
                return value
        return None

    @staticmethod
    def _extract_klipper_version_info(update_status: Any) -> dict[str, Any]:
        if not isinstance(update_status, dict):
            return {}
        version_info = update_status.get("version_info")
        if not isinstance(version_info, dict):
            return {}
        klipper = version_info.get("klipper")
        return klipper if isinstance(klipper, dict) else {}

    def _detect_firmware_flavor(self, klipper_version_info: dict[str, Any], repo_origin: str | None) -> str | None:
        owner = self._string(klipper_version_info.get("owner"))
        repo_name = self._string(klipper_version_info.get("repo_name"))
        remote_url = repo_origin or self._string(klipper_version_info.get("remote_url"))
        candidate = " ".join(item for item in (owner, repo_name, remote_url) if item)
        lowered = candidate.lower()
        if "kalicocrew" in lowered or "kalico" in lowered:
            return "Kalico"
        if "klipper3d" in lowered or "/klipper" in lowered:
            return "Klipper"
        if candidate:
            return "Custom Klipper fork"
        return None

    def _detect_host_model(self, system_info: Any) -> str | None:
        if not isinstance(system_info, dict):
            return None
        cpu_info = system_info.get("cpu_info")
        if isinstance(cpu_info, dict):
            return self._first_non_empty(
                self._string(cpu_info.get("model")),
                self._string(cpu_info.get("hardware_desc")),
                self._string(cpu_info.get("cpu_desc")),
            )
        return None

    def _detect_distribution(self, system_info: Any) -> str | None:
        if not isinstance(system_info, dict):
            return None
        distribution = system_info.get("distribution")
        if isinstance(distribution, dict):
            name = self._string(distribution.get("name"))
            version = self._string(distribution.get("version"))
            if name and version:
                return f"{name} {version}"
            return name or version
        return None

    def _extract_services(self, system_info: Any) -> list[str]:
        if not isinstance(system_info, dict):
            return []
        service_state = system_info.get("service_state")
        if not isinstance(service_state, dict):
            return []
        return sorted(str(key) for key in service_state)

    def _extract_canbus_interfaces(self, system_info: Any) -> list[str]:
        if not isinstance(system_info, dict):
            return []
        canbus = system_info.get("canbus")
        if not isinstance(canbus, dict):
            return []
        return sorted(str(key) for key in canbus)

    def _detect_git_remote(self, repo_path: str) -> str | None:
        path = Path(repo_path).expanduser()
        if not path.exists():
            return None
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
                capture_output=True,
                text=True,
                timeout=self._git_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        remote = result.stdout.strip()
        return remote or None

    def _parse_documents(self, documents: list[ConfigDocument]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for document in documents:
            current_section: str | None = None
            current_options: dict[str, str] = {}
            for raw_line in document.content.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                section_match = self._SECTION_PATTERN.match(line)
                if section_match:
                    if current_section is not None:
                        parsed.append(
                            {
                                "section": current_section,
                                "options": current_options,
                                "path": document.path,
                            }
                        )
                    current_section = section_match.group(1).strip()
                    current_options = {}
                    continue
                option_match = self._OPTION_PATTERN.match(raw_line)
                if option_match and current_section is not None:
                    current_options[option_match.group(1).strip().lower()] = option_match.group(2).strip()
            if current_section is not None:
                parsed.append(
                    {
                        "section": current_section,
                        "options": current_options,
                        "path": document.path,
                    }
                )
        return parsed

    def _detect_probe_type(self, snapshot: ConfigSnapshot, object_names: list[str]) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        document_haystack = [document.path.lower() for document in snapshot.documents]
        catalog = (
            ("beacon", ("beacon",)),
            ("eddy", ("probe_eddy_current", "eddy")),
            ("cartographer", ("cartographer",)),
            ("klicky", ("klicky", "dockable_probe")),
            ("bltouch", ("bltouch", "probe:z_virtual_endstop")),
        )
        haystacks = [*config_sections, *object_haystack, *document_haystack]
        for label, keywords in catalog:
            if any(keyword in haystack for haystack in haystacks for keyword in keywords):
                return label
        if any(section == "probe" for section in config_sections):
            return "generic"
        return "none"

    def _detect_accelerometer(self, snapshot: ConfigSnapshot, object_names: list[str]) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        haystacks = [*config_sections, *object_haystack]
        if any("adxl345" in value for value in haystacks):
            return "adxl345"
        if any("lis2dw" in value for value in haystacks):
            return "lis2dw"
        if any("resonance_tester" in value for value in haystacks):
            return "generic"
        return "none"

    def _detect_filament_sensor(self, snapshot: ConfigSnapshot) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        if any(section.startswith("filament_motion_sensor") for section in config_sections):
            return "motion"
        if any(section.startswith("filament_switch_sensor") for section in config_sections):
            return "switch"
        return "none"

    def _is_bed_mesh_configured(self, snapshot: ConfigSnapshot, object_names: list[str]) -> bool:
        if any(section.lower() == "bed_mesh" for section in snapshot.section_names):
            return True
        return any("bed_mesh" in name.lower() for name in object_names)

    def _is_input_shaper_configured(self, snapshot: ConfigSnapshot, object_names: list[str]) -> bool:
        if any(section.lower() == "input_shaper" for section in snapshot.section_names):
            return True
        return any("input_shaper" in name.lower() for name in object_names)

    def _detect_camera_stack(self, addons: list[DetectedAddon], services: list[str]) -> str:
        addon_names = {addon.name.lower() for addon in addons}
        service_names = {service.lower() for service in services}
        if "crowsnest" in addon_names or "crowsnest" in service_names:
            return "crowsnest"
        return "none"

    @staticmethod
    def _extract_mcu_sections(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for entry in parsed:
            section = str(entry.get("section", "")).strip()
            lowered = section.lower()
            if not lowered.startswith("mcu"):
                continue
            alias = section[3:].strip() if lowered != "mcu" else "mcu"
            if not alias:
                alias = "mcu"
            sections.append(
                {
                    "name": alias,
                    "section": section,
                    "options": entry.get("options", {}),
                    "path": entry.get("path"),
                }
            )
        return sections

    @staticmethod
    def _select_primary_mcu(mcu_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entry in mcu_sections:
            if str(entry.get("name", "")).lower() == "mcu":
                return entry
        return mcu_sections[0] if mcu_sections else None

    @staticmethod
    def _select_toolhead_mcu(mcu_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entry in mcu_sections:
            name = str(entry.get("name", "")).lower()
            options = entry.get("options", {})
            if name == "mcu" or name == "linux":
                continue
            if any(token in name for token in ("toolhead", "ebb", "sb", "head")):
                return entry
            if isinstance(options, dict) and options.get("canbus_uuid"):
                return entry
        return None

    def _describe_mcu(
        self,
        mcu_section: dict[str, Any] | None,
        serial_devices: list[dict[str, Any]],
        usb_devices: list[dict[str, Any]],
    ) -> str | None:
        if not mcu_section:
            return None

        options = mcu_section.get("options", {})
        if not isinstance(options, dict):
            return None

        serial_value = self._string(options.get("serial"))
        if serial_value:
            matched_serial = self._match_serial_device(serial_value, serial_devices)
            if matched_serial:
                usb_location = self._string(matched_serial.get("usb_location"))
                matched_usb = self._match_usb_device(usb_location, usb_devices)
                if matched_usb:
                    manufacturer = self._string(matched_usb.get("manufacturer"))
                    product = self._string(matched_usb.get("product"))
                    if manufacturer and product and manufacturer.lower() not in product.lower():
                        return f"{manufacturer} {product}"
                    return product or manufacturer
                device_name = self._string(matched_serial.get("path_by_id")) or self._string(matched_serial.get("device_name"))
                if device_name:
                    return device_name
            return self._extract_mcu_token(serial_value)

        canbus_uuid = self._string(options.get("canbus_uuid"))
        if canbus_uuid:
            return f"CAN UUID {canbus_uuid[:12]}"
        return None

    def _detect_toolhead_board(
        self,
        toolhead_mcu: dict[str, Any] | None,
        serial_devices: list[dict[str, Any]],
        usb_devices: list[dict[str, Any]],
        snapshot: ConfigSnapshot,
    ) -> str | None:
        explicit = self._match_named_hint(
            self._BOARD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            documents_override=self._select_toolhead_documents(snapshot),
        )
        if explicit:
            return explicit
        description = self._describe_mcu(toolhead_mcu, serial_devices, usb_devices)
        if not toolhead_mcu:
            return None
        alias = str(toolhead_mcu.get("name", "")).strip()
        if description and alias and alias.lower() != "mcu":
            return f"{alias} ({description})"
        return description

    def _detect_mainboard(
        self,
        snapshot: ConfigSnapshot,
        primary_mcu: dict[str, Any] | None,
    ) -> str | None:
        target_path = self._string(primary_mcu.get("path")) if primary_mcu else None
        return self._match_named_hint(
            self._BOARD_HINTS,
            snapshot,
            primary_mcu,
            None,
            path_filter=target_path,
        )

    def _detect_toolhead(
        self,
        snapshot: ConfigSnapshot,
        toolhead_mcu: dict[str, Any] | None,
    ) -> str | None:
        target_path = self._string(toolhead_mcu.get("path")) if toolhead_mcu else None
        scoped = self._match_named_hint(
            self._TOOLHEAD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            path_filter=target_path,
        )
        if scoped:
            return scoped
        return self._match_named_hint(
            self._TOOLHEAD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            documents_override=self._select_toolhead_documents(snapshot),
        )

    @staticmethod
    def _select_toolhead_documents(snapshot: ConfigSnapshot) -> list[ConfigDocument]:
        keywords = ("toolhead", "ebb", "sb", "stealthburner", "afterburner", "dragonburner", "orbiter", "canbus")
        matched = [
            document
            for document in snapshot.documents
            if any(keyword in document.path.lower() or keyword in document.content.lower() for keyword in keywords)
        ]
        return matched or snapshot.documents

    @staticmethod
    def _match_serial_device(serial_value: str, serial_devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        for device in serial_devices:
            for key in ("path_by_id", "path_by_hardware", "device_path"):
                candidate = device.get(key)
                if isinstance(candidate, str) and candidate == serial_value:
                    return device
        return None

    @staticmethod
    def _match_usb_device(usb_location: str | None, usb_devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not usb_location:
            return None
        for device in usb_devices:
            if str(device.get("usb_location", "")).strip() == usb_location:
                return device
        return None

    @staticmethod
    def _extract_mcu_token(value: str) -> str:
        match = re.search(r"usb-[^-_]+[_-]([A-Za-z0-9]+)", value)
        if match:
            return match.group(1)
        if "/dev/" not in value:
            return value
        return Path(value).name

    def _match_named_hint(
        self,
        catalog: tuple[tuple[str, tuple[str, ...]], ...],
        snapshot: ConfigSnapshot,
        primary_mcu: dict[str, Any] | None,
        extra_mcu: dict[str, Any] | None,
        *,
        documents_override: list[ConfigDocument] | None = None,
        path_filter: str | None = None,
    ) -> str | None:
        documents = documents_override or snapshot.documents
        if path_filter:
            filtered = [document for document in documents if document.path == path_filter]
            if filtered:
                documents = filtered
        haystacks: list[str] = [document.path.lower() for document in documents]
        haystacks.extend(document.content.lower() for document in documents)
        if primary_mcu:
            haystacks.append(str(primary_mcu).lower())
        if extra_mcu:
            haystacks.append(str(extra_mcu).lower())
        for label, keywords in catalog:
            if any(keyword in haystack for haystack in haystacks for keyword in keywords):
                return label
        return None

    def _detect_addons(
        self,
        snapshot: ConfigSnapshot,
        object_names: list[str],
        update_status: Any,
        services: list[str],
    ) -> list[DetectedAddon]:
        config_paths = [document.path.lower() for document in snapshot.documents]
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        update_haystack = []
        if isinstance(update_status, dict):
            version_info = update_status.get("version_info")
            if isinstance(version_info, dict):
                update_haystack.extend(str(key).lower() for key in version_info)
                update_haystack.extend(str(value).lower() for value in version_info.values())
        service_haystack = [service.lower() for service in services]

        detected: list[DetectedAddon] = []
        seen: set[str] = set()
        for addon_name, keywords in self._ADDON_SIGNATURES:
            source = None
            confidence: ProfileConfidence = "medium"
            detail = None
            if any(keyword in item for item in update_haystack for keyword in keywords):
                source = "Moonraker update manager"
                confidence = "high"
            elif any(keyword in item for item in object_haystack for keyword in keywords):
                source = "Loaded printer objects"
                confidence = "high"
            elif any(keyword in item for item in service_haystack for keyword in keywords):
                source = "Moonraker monitored services"
                confidence = "high"
            elif any(keyword in item for item in config_sections for keyword in keywords):
                source = "Klipper config sections"
                confidence = "medium"
            elif any(keyword in item for item in config_paths for keyword in keywords):
                source = "Klipper include paths"
                confidence = "medium"
            if not source:
                continue
            lowered_name = addon_name.lower()
            if lowered_name in seen:
                continue
            seen.add(lowered_name)
            if source == "Loaded printer objects":
                matching = next((item for item in object_haystack if any(keyword in item for keyword in keywords)), None)
                detail = matching
            detected.append(
                DetectedAddon(
                    name=addon_name,
                    source=source,
                    confidence=confidence,
                    detail=detail,
                )
            )

        detected.sort(key=lambda item: ({"high": 2, "medium": 1, "low": 0}[item.confidence], item.name), reverse=True)
        return detected
