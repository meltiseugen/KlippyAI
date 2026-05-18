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
        "[server]\n"
        "moonraker_url = http://127.0.0.1:7125\n"
        "port = 9911\n"
        "root_path = /klippyai\n"
        "data_dir = /var/lib/klippyai\n"
        "checkpoint_db = /var/lib/klippyai/checkpoints.sqlite\n\n"
        "[llm]\n"
        "llm_provider = stub\n"
        "openai_model = gpt-5-mini\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", str(cfg_path))
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.config_file == cfg_path
    assert settings.port == 9911
    assert settings.root_path == "/klippyai"
    assert settings.printer_data_root == Path("/home/pi/printer_data")
    assert settings.mainsail_config_dir == Path("/home/pi/printer_data/config")

    get_settings.cache_clear()


def test_settings_merge_cfg_with_env_secret(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "klippyai.cfg"
    cfg_path.write_text(
        "[server]\n"
        "port = 8811\n"
        "root_path = /klippyai\n\n"
        "[llm]\n"
        "llm_provider = openai\n"
        "openai_model = gpt-5-mini\n",
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
