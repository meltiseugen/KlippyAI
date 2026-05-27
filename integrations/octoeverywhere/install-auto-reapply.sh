#!/bin/sh

set -eu

usage() {
  cat <<'EOF'
Usage: install-auto-reapply.sh [options]

Install a small systemd timer that checks whether the local KlippyAI
OctoEverywhere route patch is still present. If an OctoEverywhere update
replaces the patched files, the timer reapplies the patch and restarts
OctoEverywhere.

Options:
  --install-dir PATH      KlippyAI checkout root. Default: auto-detected
  --oe-root PATH          OctoEverywhere checkout root. Default: /usr/data/octoeverywhere
  --klippyai-prefix PATH  Public KlippyAI prefix. Default: /klippyai
  --klippyai-port PORT    Local KlippyAI backend port. Default: 8811
  --nav-target VALUE      Sidebar click behavior: _blank or _self. Default: _blank
  --service NAME          OctoEverywhere systemd service. Default: octoeverywhere
  --interval VALUE        systemd timer interval. Default: 30min
  -h, --help              Show this help
EOF
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  printf 'sudo is required to run: %s\n' "$1" >&2
  exit 1
}

die() {
  printf '[KlippyAI OE auto-reapply] error: %s\n' "$*" >&2
  exit 1
}

ensure_no_spaces() {
  case "$2" in
    *" "*|*"	"*)
      die "$1 must not contain whitespace: $2"
      ;;
  esac
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
OE_ROOT="/usr/data/octoeverywhere"
KLIPPYAI_PREFIX="/klippyai"
KLIPPYAI_PORT="8811"
NAV_TARGET="_blank"
OE_SERVICE="octoeverywhere"
CHECK_INTERVAL="30min"
RUNNER_PATH="/usr/local/bin/klippyai-octoeverywhere-reapply"
SYSTEMD_DIR="/etc/systemd/system"
REAPPLY_SERVICE_NAME="klippyai-octoeverywhere-reapply.service"
REAPPLY_TIMER_NAME="klippyai-octoeverywhere-reapply.timer"

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --oe-root)
      OE_ROOT="$2"
      shift 2
      ;;
    --klippyai-prefix)
      KLIPPYAI_PREFIX="$2"
      shift 2
      ;;
    --klippyai-port)
      KLIPPYAI_PORT="$2"
      shift 2
      ;;
    --nav-target)
      NAV_TARGET="$2"
      shift 2
      ;;
    --service)
      OE_SERVICE="$2"
      shift 2
      ;;
    --interval)
      CHECK_INTERVAL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$KLIPPYAI_PREFIX" in
  "")
    KLIPPYAI_PREFIX="/klippyai"
    ;;
  /*)
    ;;
  *)
    KLIPPYAI_PREFIX="/$KLIPPYAI_PREFIX"
    ;;
esac

if [ "$KLIPPYAI_PREFIX" != "/" ]; then
  KLIPPYAI_PREFIX="${KLIPPYAI_PREFIX%/}"
fi

case "$KLIPPYAI_PORT" in
  ''|*[!0-9]*)
    die "Invalid --klippyai-port value: $KLIPPYAI_PORT"
    ;;
esac

case "$NAV_TARGET" in
  _blank|_self)
    ;;
  *)
    die "Invalid --nav-target value: $NAV_TARGET"
    ;;
esac

ensure_no_spaces "--install-dir" "$INSTALL_DIR"
ensure_no_spaces "--oe-root" "$OE_ROOT"
ensure_no_spaces "--klippyai-prefix" "$KLIPPYAI_PREFIX"
ensure_no_spaces "--service" "$OE_SERVICE"
ensure_no_spaces "--interval" "$CHECK_INTERVAL"

[ -f "$INSTALL_DIR/integrations/octoeverywhere/apply-local-klippyai-route-patch.sh" ] || \
  die "Patch helper not found under $INSTALL_DIR"
[ -d "$OE_ROOT" ] || die "OctoEverywhere checkout not found: $OE_ROOT"
command -v systemctl >/dev/null 2>&1 || die "systemctl is required."

OE_SERVICE_UNIT="$OE_SERVICE"
case "$OE_SERVICE_UNIT" in
  *.service)
    ;;
  *)
    OE_SERVICE_UNIT="${OE_SERVICE_UNIT}.service"
    ;;
esac

RUNNER_TMP=$(mktemp)
SERVICE_TMP=$(mktemp)
TIMER_TMP=$(mktemp)
cleanup() {
  rm -f "$RUNNER_TMP" "$SERVICE_TMP" "$TIMER_TMP"
}
trap cleanup EXIT

cat >"$RUNNER_TMP" <<EOF
#!/bin/sh

set -eu

INSTALL_DIR="$INSTALL_DIR"
OE_ROOT="$OE_ROOT"
KLIPPYAI_PREFIX="$KLIPPYAI_PREFIX"
KLIPPYAI_PORT="$KLIPPYAI_PORT"
NAV_TARGET="$NAV_TARGET"
OE_SERVICE="$OE_SERVICE"
SUSPEND_FILE="/etc/klippyai/octoeverywhere-reapply.suspended"

ROUTER_FILE="\$OE_ROOT/moonraker_octoeverywhere/moonrakerapirouter.py"
UI_FILE="\$OE_ROOT/moonraker_octoeverywhere/static/oe-ui.js"
PATCH_SCRIPT="\$INSTALL_DIR/integrations/octoeverywhere/apply-local-klippyai-route-patch.sh"

log() {
  printf '[KlippyAI OE auto-reapply] %s\n' "\$*"
}

patch_is_present() {
  [ -f "\$ROUTER_FILE" ] || return 1
  [ -f "\$UI_FILE" ] || return 1
  grep -q "KlippyAI local route patch init start" "\$ROUTER_FILE" || return 1
  grep -q "KlippyAI local route patch map start" "\$ROUTER_FILE" || return 1
  grep -q "KlippyAI local route patch start" "\$UI_FILE" || return 1
  grep -q "oe_open_klippyai_popup_directly" "\$UI_FILE" || return 1
  return 0
}

if patch_is_present; then
  log "OctoEverywhere patch is present; nothing to do."
  exit 0
fi

if [ -f "\$SUSPEND_FILE" ]; then
  log "Auto-reapply is suspended by \$SUSPEND_FILE; leaving OctoEverywhere repo clean for update."
  exit 0
fi

[ -f "\$PATCH_SCRIPT" ] || {
  log "Patch helper is missing: \$PATCH_SCRIPT"
  exit 1
}

log "OctoEverywhere patch is missing or incomplete; reapplying."
sh "\$PATCH_SCRIPT" \
  --oe-root "\$OE_ROOT" \
  --klippyai-prefix "\$KLIPPYAI_PREFIX" \
  --klippyai-port "\$KLIPPYAI_PORT" \
  --nav-target "\$NAV_TARGET" \
  --restart-service \
  --service "\$OE_SERVICE"
EOF

cat >"$SERVICE_TMP" <<EOF
[Unit]
Description=Reapply KlippyAI OctoEverywhere local route patch when missing
After=network-online.target $OE_SERVICE_UNIT
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$RUNNER_PATH
EOF

cat >"$TIMER_TMP" <<EOF
[Unit]
Description=Check whether the KlippyAI OctoEverywhere patch still exists

[Timer]
OnBootSec=2min
OnUnitActiveSec=$CHECK_INTERVAL
AccuracySec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

run_root install -d -m 755 "$(dirname "$RUNNER_PATH")" "$SYSTEMD_DIR"
run_root install -m 755 "$RUNNER_TMP" "$RUNNER_PATH"
run_root install -m 644 "$SERVICE_TMP" "$SYSTEMD_DIR/$REAPPLY_SERVICE_NAME"
run_root install -m 644 "$TIMER_TMP" "$SYSTEMD_DIR/$REAPPLY_TIMER_NAME"
run_root systemctl daemon-reload
run_root "$RUNNER_PATH"
run_root systemctl enable --now "$REAPPLY_TIMER_NAME"

printf '[KlippyAI OE auto-reapply] Installed %s\n' "$RUNNER_PATH"
printf '[KlippyAI OE auto-reapply] Installed %s/%s\n' "$SYSTEMD_DIR" "$REAPPLY_SERVICE_NAME"
printf '[KlippyAI OE auto-reapply] Installed %s/%s\n' "$SYSTEMD_DIR" "$REAPPLY_TIMER_NAME"
printf '[KlippyAI OE auto-reapply] Timer interval: %s\n' "$CHECK_INTERVAL"
