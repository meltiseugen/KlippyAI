#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$SCRIPT_DIR/patches/mainsail-v2.17.0-klippyai-shell.patch"
EXPECTED_COMMIT="6130a0aa1776a138feaab691b9e4b1334b676b79"

die() {
  printf '[KlippyAI mainsail] error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[KlippyAI mainsail] %s\n' "$*"
}

TARGET_DIR="${1:-}"

[[ -n "$TARGET_DIR" ]] || die "Usage: ./integrations/mainsail/apply-patch.sh /path/to/mainsail"
[[ -d "$TARGET_DIR" ]] || die "Target directory does not exist: $TARGET_DIR"
[[ -d "$TARGET_DIR/.git" ]] || die "Target directory is not a git checkout: $TARGET_DIR"
[[ -f "$TARGET_DIR/package.json" ]] || die "Target directory does not look like a Mainsail checkout: $TARGET_DIR"
[[ -f "$PATCH_FILE" ]] || die "Patch file not found: $PATCH_FILE"

TARGET_COMMIT="$(git -C "$TARGET_DIR" rev-parse HEAD)"
if [[ "$TARGET_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  log "Target commit is $TARGET_COMMIT"
  log "Patch was authored against $EXPECTED_COMMIT"
  log "Continuing anyway, but conflicts are more likely."
fi

git -C "$TARGET_DIR" apply --check "$PATCH_FILE"
git -C "$TARGET_DIR" apply "$PATCH_FILE"

log "Patch applied successfully."
log "Next steps:"
log "  cd \"$TARGET_DIR\""
log "  npm install"
log "  npm run build"

