from __future__ import annotations

from pathlib import Path

from klippyai_agent.settings import get_settings


def test_settings_load_values_from_klippyai_cfg(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[install]\n"
        "printer_data_root: /home/pi/printer_data  # Printer data root\n"
        "mainsail_config_dir: /home/pi/printer_data/config  # Mainsail config dir\n\n"
        "[printer_identity]\n"
        "mainboard: BTT Octopus Pro  # Controller board\n"
        "toolhead: BTT EBB36  # Toolhead board\n\n"
        "[printer_capabilities]\n"
        "probe_type: beacon  # Probe type\n"
        "filament_sensor: none  # Filament sensor family\n"
        "bed_mesh_configured: true  # Bed mesh enabled\n\n"
        "[config_context]\n"
        "root_config_file: machines/voron/printer-main.cfg  # Config root file\n"
        "ignore_globs: backups/**, archive/**  # Ignore globs\n\n"
        "[server]\n"
        "port: 9911  # Port\n"
        "root_path: /klippyai  # Root path\n"
        "data_dir: /var/lib/klippyai  # Data dir\n"
        "checkpoint_db: /var/lib/klippyai/checkpoints.sqlite  # Checkpoint db\n"
        "enable_write_actions: true  # Should still coerce false\n\n"
        "[chat]\n"
        "conversation_history_pairs: 7  # Previous chat pairs\n\n"
        "[logs]\n"
        "logs_dir_path: /home/pi/printer_data/logs  # Log dir\n"
        "agent_log_file_name: klippyai.log  # Agent log name\n"
        "agent_log_level: debug  # Log level\n"
        "excluded_logs: klippyai.log, crowsnest, *_debug.log  # Excluded logs\n"
        "log_tail_lines_default: 100  # Default tail lines\n\n"
        "[log_tail_lines]\n"
        "klippy: 120  # Override\n"
        "moonraker: 220  # Override\n\n"
        "[llm]\n"
        "llm_provider: stub  # Provider\n"
        "openai_model: gpt-5.4-mini  # Model\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("KLIPPYAI_MOONRAKER_URL", "http://127.0.0.1:7125")
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.config_file == cfg_path
    assert settings.port == 9911
    assert settings.root_path == "/klippyai"
    assert settings.public_base_url == "http://127.0.0.1:9911"
    assert settings.moonraker_url == "http://127.0.0.1:7125"
    assert settings.enable_write_actions is False
    assert settings.conversation_history_pairs == 7
    assert settings.agent_log_level == "DEBUG"
    assert settings.agent_log_path() == Path("/home/pi/printer_data/logs/klippyai.log")
    assert settings.printer_data_root == Path("/home/pi/printer_data")
    assert settings.mainsail_config_dir == Path("/home/pi/printer_data/config")
    assert settings.mainboard == "BTT Octopus Pro"
    assert settings.toolhead == "BTT EBB36"
    assert settings.probe_type == "beacon"
    assert settings.filament_sensor == "none"
    assert settings.bed_mesh_configured is True
    assert settings.config_root_file == "machines/voron/printer-main.cfg"
    assert settings.config_ignore_globs == "backups/**, archive/**"
    assert settings.log_tail_lines_default == 100
    assert settings.log_tail_lines_overrides == {"klippy": 120, "moonraker": 220}
    assert settings.excluded_logs == ["klippyai.log", "crowsnest", "*_debug.log"]

    get_settings.cache_clear()


def test_settings_merge_cfg_with_env_secret(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[server]\n"
        "port: 8811\n"
        "root_path: /klippyai\n\n"
        "[llm]\n"
        "llm_provider: openai\n"
        "openai_model: gpt-5.4-mini\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("KLIPPYAI_OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.port == 8811
    assert settings.llm_provider == "openai"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-openai-key"

    get_settings.cache_clear()


def test_settings_load_without_printer_geometry_section(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[printer_identity]\n"
        "mainboard: BTT Octopus Pro\n\n"
        "[printer_capabilities]\n"
        "bed_mesh_configured: true\n"
        "addons: Beacon\n\n"
        "[server]\n"
        "port: 8811\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", str(cfg_path))
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.mainboard == "BTT Octopus Pro"
    assert settings.bed_mesh_configured is True
    assert settings.addons == "Beacon"
    assert settings.port == 8811

    get_settings.cache_clear()
