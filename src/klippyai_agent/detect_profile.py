from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from klippyai_agent.moonraker import MoonrakerClient, MoonrakerError
from klippyai_agent.printerconfig import ConfigCollector
from klippyai_agent.printerprofile import PrinterProfileCollector, write_profile_to_cfg


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect printer profile data and persist it to klippyai.cfg.")
    parser.add_argument("--config-file", required=True, help="Path to klippyai.cfg")
    parser.add_argument("--moonraker-url", required=True, help="Moonraker base URL")
    parser.add_argument("--printer-data-root", required=True, help="Printer data root directory")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing printer profile section values instead of only filling blanks.",
    )
    return parser


async def _run_detection(args: argparse.Namespace) -> int:
    config_file = Path(args.config_file).expanduser()
    if not config_file.exists():
        raise FileNotFoundError(f"Config file does not exist: {config_file}")

    moonraker = MoonrakerClient(args.moonraker_url)
    printer_data_root = Path(args.printer_data_root).expanduser()
    root_config_override = await _detect_root_config_override(moonraker, printer_data_root)
    try:
        config_collector = ConfigCollector(
            printer_data_root,
            root_config_name=root_config_override,
        )
        collector = PrinterProfileCollector(
            moonraker,
            config_collector,
        )
        config_snapshot = config_collector.collect()
        profile = await collector.collect(config_snapshot)
    finally:
        await moonraker.aclose()

    write_profile_to_cfg(
        config_file,
        profile,
        root_config_file=_normalize_root_config_setting(config_snapshot.root_file, printer_data_root),
        overwrite=bool(args.overwrite),
    )

    summary = profile.summary_label() or "no profile summary detected"
    print(f"[KlippyAI] Detected printer profile: {summary}")
    if config_snapshot.root_file:
        print(f"[KlippyAI] Active root config: {config_snapshot.root_file}")
    if profile.notes:
        for note in profile.notes[:8]:
            print(f"[KlippyAI] note: {note}")
    return 0


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_detection(args)))


async def _detect_root_config_override(
    moonraker: MoonrakerClient,
    printer_data_root: Path,
) -> str | None:
    try:
        printer_info = await moonraker.get_printer_info()
    except MoonrakerError:
        return None

    for key in ("config_file", "config_path", "config_filename"):
        candidate = printer_info.get(key)
        normalized = _normalize_root_config_setting(candidate, printer_data_root)
        if normalized:
            return normalized
    return None


def _normalize_root_config_setting(value: object, printer_data_root: Path) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    path = Path(raw).expanduser()
    config_dir = printer_data_root / "config"
    if not path.is_absolute():
        return path.as_posix()

    try:
        return path.relative_to(config_dir).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    main()
