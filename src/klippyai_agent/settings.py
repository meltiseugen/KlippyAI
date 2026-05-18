from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
