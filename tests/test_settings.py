from __future__ import annotations

from pathlib import Path

from klippyai_agent.settings import get_settings


def test_settings_load_values_from_klippyai_cfg(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[install]\n"
        "service_user = pi\n"
        "project_checkout_path = /home/pi/KlippyAI\n"
        "printer_data_root = /home/pi/printer_data\n"
        "mainsail_config_dir = /home/pi/printer_data/config\n\n"
        "[printer_identity]\n"
        "mainboard = BTT Octopus Pro\n"
        "toolhead = Stealthburner\n\n"
        "[printer_capabilities]\n"
        "probe_type = beacon\n"
        "filament_sensor = none\n"
        "bed_mesh_configured = true\n\n"
        "[printer_geometry]\n"
        "kinematics = corexy\n"
        "build_volume_x = 350\n"
        "extruder_count = 1\n\n"
        "[config_context]\n"
        "root_config_file = machines/voron/printer-main.cfg\n"
        "ignore_globs = backups/**, archive/**\n\n"
        "[server]\n"
        "moonraker_url = http://127.0.0.1:7125\n"
        "port = 9911\n"
        "root_path = /klippyai\n"
        "data_dir = /var/lib/klippyai\n"
        "checkpoint_db = /var/lib/klippyai/checkpoints.sqlite\n"
        "enable_write_actions = true\n\n"
        "[logs]\n"
        "logs_dir_name = logs\n"
        "agent_log_file_name = klippyai.log\n"
        "agent_log_level = debug\n"
        "agent_log_max_bytes = 4096\n"
        "agent_log_backup_count = 2\n\n"
        "[llm]\n"
        "llm_provider = stub\n"
        "openai_model = gpt-5.4-mini\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", str(cfg_path))
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.config_file == cfg_path
    assert settings.port == 9911
    assert settings.root_path == "/klippyai"
    assert settings.enable_write_actions is False
    assert settings.agent_log_level == "DEBUG"
    assert settings.agent_log_path() == Path("/home/pi/printer_data/logs/klippyai.log")
    assert settings.printer_data_root == Path("/home/pi/printer_data")
    assert settings.mainsail_config_dir == Path("/home/pi/printer_data/config")
    assert settings.mainboard == "BTT Octopus Pro"
    assert settings.toolhead == "Stealthburner"
    assert settings.probe_type == "beacon"
    assert settings.filament_sensor == "none"
    assert settings.bed_mesh_configured is True
    assert settings.kinematics == "corexy"
    assert settings.build_volume_x == 350
    assert settings.extruder_count == 1
    assert settings.config_root_file == "machines/voron/printer-main.cfg"
    assert settings.config_ignore_globs == "backups/**, archive/**"

    get_settings.cache_clear()


def test_settings_merge_cfg_with_env_secret(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[server]\n"
        "port = 8811\n"
        "root_path = /klippyai\n\n"
        "[llm]\n"
        "llm_provider = openai\n"
        "openai_model = gpt-5.4-mini\n",
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
