#!/usr/bin/env bash

set -euo pipefail

TITLE="KlippyAI"
HREF="/klippyai/"
TARGET="_blank"
POSITION="85"
ICON=""
CONFIG_DIR=""

usage() {
  cat <<'EOF'
Usage:
  install-custom-nav.sh --config-dir /path/to/printer_data/config [options]

Options:
  --config-dir PATH   Printer config directory that contains the .theme folder
  --href PATH         Target link for the Mainsail navigation entry
  --title TEXT        Navigation label
  --target VALUE      Link target, usually _self or _blank
  --position NUMBER   Navigation sort position
  --icon SVG_PATH     Optional MDI SVG path string
  -h, --help          Show this help text
EOF
}

die() {
  printf '[KlippyAI] error: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir)
      CONFIG_DIR="${2:-}"
      shift 2
      ;;
    --href)
      HREF="${2:-}"
      shift 2
      ;;
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --position)
      POSITION="${2:-}"
      shift 2
      ;;
    --icon)
      ICON="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$CONFIG_DIR" ]] || die "--config-dir is required."
command -v python3 >/dev/null 2>&1 || die "python3 is required."
[[ -d "$CONFIG_DIR" ]] || die "Config directory does not exist: $CONFIG_DIR"
[[ "$POSITION" =~ ^[0-9]+$ ]] || die "--position must be numeric."
[[ "$TARGET" == "_self" || "$TARGET" == "_blank" ]] || die "--target must be _self or _blank."

THEME_DIR="${CONFIG_DIR%/}/.theme"
NAVI_FILE="${THEME_DIR}/navi.json"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

mkdir -p "$THEME_DIR"

if [[ -f "$NAVI_FILE" ]]; then
  cp "$NAVI_FILE" "${NAVI_FILE}.bak.${TIMESTAMP}"
fi

python3 - "$NAVI_FILE" "$TITLE" "$HREF" "$TARGET" "$POSITION" "$ICON" <<'PY'
import json
import sys
from pathlib import Path

navi_file = Path(sys.argv[1])
title = sys.argv[2]
href = sys.argv[3]
target = sys.argv[4]
position = int(sys.argv[5])
icon = sys.argv[6]

entry = {
    "title": title,
    "href": href,
    "target": target,
    "position": position,
}
if icon:
    entry["icon"] = icon

items = []
if navi_file.exists():
    try:
        loaded = json.loads(navi_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Existing navi.json is not valid JSON: {exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit("Existing navi.json must contain a JSON array.")
    items = loaded

filtered = []
for item in items:
    if not isinstance(item, dict):
        filtered.append(item)
        continue
    same_href = item.get("href") == href
    same_title = item.get("title") == title
    if same_href or same_title:
        continue
    filtered.append(item)

filtered.append(entry)

def sort_key(value):
    if isinstance(value, dict):
        position_value = value.get("position")
        if isinstance(position_value, int):
            order = position_value
        else:
            order = 9999
        title_value = str(value.get("title", ""))
        return (order, title_value.lower())
    return (9999, str(value).lower())

filtered.sort(key=sort_key)
navi_file.write_text(json.dumps(filtered, indent=2) + "\n", encoding="utf-8")
PY

printf '[KlippyAI] Wrote %s\n' "$NAVI_FILE"
