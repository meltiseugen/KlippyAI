from __future__ import annotations

from pathlib import Path

import pytest

from klippyai_agent.printerconfig import ConfigCollector
from klippyai_agent.printerprofile import (
    PrinterProfileCollector,
    build_profile_from_settings,
    write_profile_to_cfg,
)
from klippyai_agent.settings import Settings


class _FakeMoonraker:
    async def get_server_info(self) -> dict[str, object]:
        return {"components": ["update_manager"]}

    async def get_printer_info(self) -> dict[str, object]:
        return {
            "software_version": "v1.0.0",
            "state": "ready",
            "state_message": "Printer is ready",
            "klipper_path": "/srv/klipper",
            "config_file": "/home/pi/printer_data/config/printer.cfg",
        }

    async def list_printer_objects(self) -> list[str]:
        return [
            "gcode",
            "configfile",
            "bed_mesh",
            "beacon",
            "probe_eddy_current my_eddy",
            "input_shaper",
            "adxl345 toolhead",
        ]

    async def get_system_info(self) -> dict[str, object]:
        return {
            "cpu_info": {
                "model": "Raspberry Pi 4 Model B Rev 1.5",
            },
            "distribution": {
                "name": "Debian GNU/Linux",
                "version": "12",
            },
            "service_state": {
                "klipper": {},
                "moonraker": {},
                "crowsnest": {},
            },
            "canbus": {
                "can0": {},
            },
        }

    async def get_update_status(self) -> dict[str, object]:
        return {
            "version_info": {
                "klipper": {
                    "remote_url": "https://github.com/KalicoCrew/kalico.git",
                    "owner": "KalicoCrew",
                    "repo_name": "kalico",
                    "version": "v1.2.3",
                },
                "octoeverywhere": {
                    "configured_type": "git_repo",
                    "name": "octoeverywhere",
                },
            }
        }

    async def list_serial_devices(self) -> list[dict[str, object]]:
        return [
            {
                "device_path": "/dev/ttyACM0",
                "device_name": "ttyACM0",
                "path_by_id": "/dev/serial/by-id/usb-Klipper_stm32f446xx_12345-if00",
                "path_by_hardware": "/dev/serial/by-path/platform-usb-0:1.4:1.0",
                "usb_location": "1:4",
            }
        ]

    async def list_usb_devices(self) -> list[dict[str, object]]:
        return [
            {
                "usb_location": "1:4",
                "manufacturer": "Klipper",
                "product": "stm32f446xx",
            }
        ]


@pytest.mark.asyncio
async def test_profile_collector_detects_firmware_addons_and_board_hints(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)

    (config_dir / "printer.cfg").write_text(
        "[include extras/stealthburner_ebb36.cfg]\n"
        "[include klippyai/*.cfg]\n\n"
        "[printer]\n"
        "kinematics: corexy\n\n"
        "[stepper_x]\n"
        "position_max: 350\n\n"
        "[stepper_y]\n"
        "position_max: 350\n\n"
        "[stepper_z]\n"
        "position_max: 330\n\n"
        "[extruder]\n"
        "step_pin: test\n\n"
        "[filament_switch_sensor runout]\n"
        "switch_pin: ^PA2\n\n"
        "[input_shaper]\n"
        "shaper_type_x: mzv\n"
        "shaper_freq_x: 60.0\n\n"
        "[mcu]\n"
        "serial: /dev/serial/by-id/usb-Klipper_stm32f446xx_12345-if00\n\n"
        "[mcu toolhead]\n"
        "canbus_uuid: 1234567890ab\n",
        encoding="utf-8",
    )
    (extras_dir / "stealthburner_ebb36.cfg").write_text(
        "[beacon]\n"
        "x_offset: 0\n\n"
        "[adxl345]\n"
        "cs_pin: toolhead:PA15\n",
        encoding="utf-8",
    )

    collector = PrinterProfileCollector(
        _FakeMoonraker(),  # type: ignore[arg-type]
        ConfigCollector(tmp_path / "printer_data"),
    )

    profile = await collector.collect()

    addon_names = {addon.name for addon in profile.addons}

    assert profile.firmware_flavor == "Kalico"
    assert profile.firmware_version == "v1.2.3"
    assert profile.host_model == "Raspberry Pi 4 Model B Rev 1.5"
    assert profile.host_distribution == "Debian GNU/Linux 12"
    assert profile.mainboard_mcu == "Klipper stm32f446xx"
    assert profile.toolhead_board == "BTT EBB36"
    assert profile.toolhead == "Stealthburner"
    assert profile.probe_type == "beacon"
    assert profile.accelerometer == "adxl345"
    assert profile.filament_sensor == "switch"
    assert profile.camera_stack == "crowsnest"
    assert profile.bed_mesh_configured is True
    assert profile.input_shaper_configured is True
    assert profile.canbus_enabled is True
    assert "Beacon" in addon_names
    assert "Eddy" in addon_names
    assert "Crowsnest" in addon_names
    assert "OctoEverywhere" in addon_names


@pytest.mark.asyncio
async def test_profile_collector_applies_mainboard_and_toolhead_overrides(tmp_path: Path) -> None:
    config_dir = tmp_path / "printer_data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "printer.cfg").write_text(
        "[printer]\n"
        "kinematics: cartesian\n\n"
        "[mcu]\n"
        "serial: /dev/serial/by-id/usb-Klipper_stm32f446xx_12345-if00\n",
        encoding="utf-8",
    )

    collector = PrinterProfileCollector(
        _FakeMoonraker(),  # type: ignore[arg-type]
        ConfigCollector(tmp_path / "printer_data"),
        mainboard_override="LDO Leviathan",
        toolhead_override="Dragon Burner",
    )

    profile = await collector.collect()

    assert profile.mainboard == "LDO Leviathan"
    assert profile.toolhead == "Dragon Burner"
    assert any(item.source == "klippyai.cfg" and "Mainboard declared" in item.summary for item in profile.evidence)
    assert any(item.source == "klippyai.cfg" and "Toolhead declared" in item.summary for item in profile.evidence)


def test_build_profile_from_settings_uses_persisted_identity() -> None:
    settings = Settings(
        firmware_flavor="Kalico",
        firmware_version="v1.2.3",
        host_model="Raspberry Pi 4",
        host_distribution="Debian 12",
        mainboard="BTT Octopus Pro",
        mainboard_mcu="stm32f446xx",
        toolhead="BTT EBB36",
        probe_type="beacon",
        accelerometer="adxl345",
        filament_sensor="none",
        camera_stack="crowsnest",
        bed_mesh_configured=True,
        input_shaper_configured=True,
        canbus_enabled=True,
        addons="Beacon, Eddy, Crowsnest",
    )

    profile = build_profile_from_settings(settings)

    assert profile.firmware_flavor == "Kalico"
    assert profile.mainboard == "BTT Octopus Pro"
    assert profile.toolhead is None
    assert profile.toolhead_board == "BTT EBB36"
    assert profile.probe_type == "beacon"
    assert profile.filament_sensor == "none"
    assert profile.bed_mesh_configured is True
    assert profile.canbus_enabled is True
    assert [addon.name for addon in profile.addons] == ["Beacon", "Eddy", "Crowsnest"]


@pytest.mark.asyncio
async def test_write_profile_to_cfg_persists_detected_identity(tmp_path: Path) -> None:
    config_file = tmp_path / "klippyai.cfg"
    config_file.write_text(
        "# Firmware comment should be preserved\n"
        "[printer_identity]\n"
        "# Main firmware flavor running on the printer stack.\n"
        "firmware_flavor:\n"
        "mainboard:\n"
        "mainboard_mcu: legacy\n"
        "toolhead:\n"
        "toolhead_board: legacy\n"
        "\n[printer_capabilities]\n"
        "# Installed probe family, or none when no probe is present.\n"
        "canbus_enabled: false\n"
        "camera_stack: legacy\n"
        "addons:\n"
        "\n[printer_geometry]\n"
        "kinematics: corexy\n"
        "build_volume_x: 350\n"
        "extruder_count: 1\n",
        encoding="utf-8",
    )

    config_dir = tmp_path / "printer_data" / "config"
    extras_dir = config_dir / "extras"
    extras_dir.mkdir(parents=True)
    (config_dir / "printer.cfg").write_text(
        "[include extras/stealthburner_ebb36.cfg]\n"
        "[printer]\n"
        "kinematics: corexy\n\n"
        "[stepper_x]\n"
        "position_max: 350\n\n"
        "[stepper_y]\n"
        "position_max: 350\n\n"
        "[stepper_z]\n"
        "position_max: 330\n\n"
        "[extruder]\n"
        "step_pin: test\n\n"
        "[filament_switch_sensor runout]\n"
        "switch_pin: ^PA2\n\n"
        "[input_shaper]\n"
        "shaper_type_x: mzv\n"
        "shaper_freq_x: 60.0\n\n"
        "[mcu]\n"
        "serial: /dev/serial/by-id/usb-Klipper_stm32f446xx_12345-if00\n\n"
        "[mcu toolhead]\n"
        "canbus_uuid: 1234567890ab\n",
        encoding="utf-8",
    )
    (extras_dir / "stealthburner_ebb36.cfg").write_text(
        "[beacon]\n"
        "x_offset: 0\n\n"
        "[adxl345]\n"
        "cs_pin: toolhead:PA15\n",
        encoding="utf-8",
    )

    collector = PrinterProfileCollector(
        _FakeMoonraker(),  # type: ignore[arg-type]
        ConfigCollector(tmp_path / "printer_data"),
    )
    profile = await collector.collect()
    write_profile_to_cfg(config_file, profile, root_config_file="printer.cfg")

    contents = config_file.read_text(encoding="utf-8")
    assert "# Firmware comment should be preserved" in contents
    assert "# Main firmware flavor running on the printer stack." in contents
    assert "# Installed probe family, or none when no probe is present." in contents
    assert "firmware_flavor: Kalico" in contents
    assert "toolhead: BTT EBB36" in contents
    assert "probe_type: beacon" in contents
    assert "accelerometer: adxl345" in contents
    assert "filament_sensor: switch" in contents
    assert "bed_mesh_configured: true" in contents
    assert "input_shaper_configured: true" in contents
    assert "canbus_enabled: true" in contents
    assert "root_config_file: printer.cfg" in contents
    assert "[printer_geometry]" not in contents
    assert "mainboard_mcu:" not in contents
    assert "toolhead_board:" not in contents
    assert "camera_stack:" not in contents
