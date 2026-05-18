from __future__ import annotations

import configparser
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr
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
    openai_model: str = "gpt-5-mini"
    openai_api_key: SecretStr | None = None
    enable_write_actions: bool = False

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)


def _load_klippyai_cfg_values(config_file: Path) -> dict[str, Any]:
    if not config_file.exists() or not config_file.is_file():
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_file, encoding="utf-8")

    field_names = set(Settings.model_fields)
    values: dict[str, Any] = {}
    for section in parser.sections():
        for key, value in parser.items(section):
            normalized_key = key.strip().lower()
            if normalized_key in field_names:
                values[normalized_key] = value.strip()
    return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    bootstrap = Settings()
    cfg_values = _load_klippyai_cfg_values(bootstrap.config_file)
    return Settings(**cfg_values)
