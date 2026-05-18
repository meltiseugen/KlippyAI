#!/usr/bin/env bash

set -euo pipefail

TITLE="KlippyAI"
HREF="/klippyai/"
CONFIG_DIR=""

usage() {
  cat <<'EOF'
Usage:
  uninstall-custom-nav.sh --config-dir /path/to/printer_data/config [options]

Options:
  --config-dir PATH   Printer config directory that contains the .theme folder
  --href PATH         Target link for the Mainsail navigation entry
  --title TEXT        Navigation label
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

NAVI_FILE="${CONFIG_DIR%/}/.theme/navi.json"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

if [[ ! -f "$NAVI_FILE" ]]; then
  printf '[KlippyAI] No custom navigation file found at %s\n' "$NAVI_FILE"
  exit 0
fi

cp "$NAVI_FILE" "${NAVI_FILE}.bak.${TIMESTAMP}"

python3 - "$NAVI_FILE" "$TITLE" "$HREF" <<'PY'
import json
import sys
from pathlib import Path

navi_file = Path(sys.argv[1])
title = sys.argv[2]
href = sys.argv[3]

try:
    loaded = json.loads(navi_file.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    raise SystemExit(f"Existing navi.json is not valid JSON: {exc}") from exc

if not isinstance(loaded, list):
    raise SystemExit("Existing navi.json must contain a JSON array.")

filtered = []
for item in loaded:
    if not isinstance(item, dict):
        filtered.append(item)
        continue
    same_href = item.get("href") == href
    same_title = item.get("title") == title
    if same_href or same_title:
        continue
    filtered.append(item)

navi_file.write_text(json.dumps(filtered, indent=2) + "\n", encoding="utf-8")
PY

printf '[KlippyAI] Updated %s\n' "$NAVI_FILE"
