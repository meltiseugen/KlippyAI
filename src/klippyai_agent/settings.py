from __future__ import annotations

import configparser
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KLIPPYAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "KlippyAI"
    environment: str = "development"
    config_file: Path = Path("/home/pi/printer_data/config/klippyai.cfg")
    service_user: str = "pi"
    project_checkout_path: Path = Path("/home/pi/KlippyAI")
    mainsail_config_dir: Path = Path("/home/pi/printer_data/config")
    config_root_file: str | None = None
    config_ignore_globs: str | None = None
    firmware_flavor: str | None = None
    firmware_version: str | None = None
    host_model: str | None = None
    host_distribution: str | None = None
    kinematics: str | None = None
    mainboard: str | None = None
    mainboard_mcu: str | None = None
    toolhead: str | None = None
    toolhead_board: str | None = None
    probe_type: str | None = None
    accelerometer: str | None = None
    filament_sensor: str | None = None
    camera_stack: str | None = None
    build_volume_x: float | None = None
    build_volume_y: float | None = None
    build_volume_z: float | None = None
    extruder_count: int | None = None
    bed_mesh_configured: bool = False
    input_shaper_configured: bool = False
    canbus_enabled: bool = False
    addons: str | None = None
    host: str = "127.0.0.1"
    port: int = 8811
    root_path: str = ""
    public_base_url: str = "http://127.0.0.1:8811"
    moonraker_url: str = "http://127.0.0.1:7125"
    data_dir: Path = Path(".local/klippyai")
    checkpoint_db: Path = Path(".local/klippyai/checkpoints.sqlite")
    printer_data_root: Path = Path("/home/pi/printer_data")
    managed_config_dir_name: str = "klippyai"
    session_ttl_seconds: int = 3600
    collect_host_logs: bool = True
    logs_dir_name: str = "logs"
    agent_log_file_name: str = "klippyai.log"
    agent_log_level: str = "INFO"
    agent_log_max_bytes: int = 2_097_152
    agent_log_backup_count: int = 5
    log_max_files_per_family: int = 3
    log_active_tail_bytes: int = 160_000
    log_rotated_tail_bytes: int = 80_000
    log_artifact_char_limit: int = 18_000
    collect_systemd_diagnostics: bool = True
    moonraker_service_name: str = "moonraker.service"
    klipper_service_name: str = "klipper.service"
    journal_lines: int = 200
    system_status_artifact_char_limit: int = 6_000
    journal_artifact_char_limit: int = 16_000
    system_command_timeout_seconds: float = 6.0
    llm_provider: str = "stub"
    openai_model: str = "gpt-5.4-mini"
    openai_api_key: SecretStr | None = None
    enable_write_actions: bool = False

    @field_validator(
        "firmware_flavor",
        "firmware_version",
        "config_root_file",
        "config_ignore_globs",
        "host_model",
        "host_distribution",
        "kinematics",
        "mainboard",
        "mainboard_mcu",
        "toolhead",
        "toolhead_board",
        "probe_type",
        "accelerometer",
        "filament_sensor",
        "camera_stack",
        "addons",
        mode="before",
    )
    @classmethod
    def _normalize_optional_identity(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("agent_log_file_name", "agent_log_level", mode="before")
    @classmethod
    def _normalize_required_strings(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Logging settings must not be blank.")
        return normalized

    @model_validator(mode="after")
    def _enforce_read_only_runtime(self) -> "Settings":
        # KlippyAI runtime is intentionally shackled for now. Keep the flag for
        # forward compatibility, but do not allow it to enable file writes.
        self.enable_write_actions = False
        self.agent_log_level = self.agent_log_level.upper()
        return self

    def host_logs_dir(self) -> Path:
        return self.printer_data_root / self.logs_dir_name

    def agent_log_path(self) -> Path:
        return self.host_logs_dir() / self.agent_log_file_name

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        self.host_logs_dir().mkdir(parents=True, exist_ok=True)


def _load_klippyai_cfg_values(config_file: Path) -> dict[str, Any]:
    if not config_file.exists() or not config_file.is_file():
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_file, encoding="utf-8")

    field_names = set(Settings.model_fields)
    section_aliases: dict[str, dict[str, str]] = {
        "config_context": {
            "root_config_file": "config_root_file",
            "ignore_globs": "config_ignore_globs",
        }
    }
    values: dict[str, Any] = {}
    for section in parser.sections():
        normalized_section = section.strip().lower()
        for key, value in parser.items(section):
            normalized_key = key.strip().lower()
            normalized_key = section_aliases.get(normalized_section, {}).get(normalized_key, normalized_key)
            if normalized_key in field_names:
                values[normalized_key] = value.strip()
    return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    bootstrap = Settings()
    cfg_values = _load_klippyai_cfg_values(bootstrap.config_file)
    return Settings(**cfg_values)
