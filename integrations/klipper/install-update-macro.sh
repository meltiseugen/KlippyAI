#!/bin/sh

set -eu

usage() {
  cat <<'EOF'
Usage: install-update-macro.sh [options]

Install the optional UPDATE_KLIPPYAI Klipper macro. The macro uses
gcode_shell_command to run a narrow helper that pulls the KlippyAI checkout,
refreshes the editable Python install, and restarts klippyai-agent.

Options:
  --install-dir PATH       KlippyAI checkout root. Default: auto-detected
  --install-user USER      User that owns/runs the KlippyAI checkout. Default: env or current user
  --config-dir PATH        Klipper config directory. Default: /usr/data/printer_data/config when present
  --root-config PATH       Root printer config. Default: CONFIG_DIR/printer.cfg
  --klipper-checkout PATH  Klipper/Kalico checkout. Default: auto-detected
  --install-gcode-shell-command
                           Install gcode_shell_command.py first if it is missing
  --klippyai-service NAME  KlippyAI systemd service. Default: klippyai-agent
  --klipper-service NAME   Klipper systemd service. Default: klipper.service
  --restart-klipper        Restart Klipper after writing the macro
  -h, --help               Show this help
EOF
}

die() {
  printf '[KlippyAI update macro] error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[KlippyAI update macro] %s\n' "$*"
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

  die "sudo is required to run: $1"
}

extract_env_value() {
  path="$1"
  key="$2"
  [ -f "$path" ] || return 1
  line=$(grep -E "^${key}=" "$path" | tail -n1 || true)
  [ -n "$line" ] || return 1
  line=${line#*=}
  case "$line" in
    \"*\")
      line=${line#\"}
      line=${line%\"}
      ;;
  esac
  printf '%s' "$line"
}

has_gcode_shell_command_support() {
  [ -n "$KLIPPER_CHECKOUT" ] && [ -f "$KLIPPER_CHECKOUT/klippy/extras/gcode_shell_command.py" ] && return 0
  find /usr/data /root /opt /usr/local /usr/share -maxdepth 6 \
    -type f -path '*/klippy/extras/gcode_shell_command.py' 2>/dev/null | grep -q .
}

detect_klipper_checkout() {
  candidate=""
  for candidate in \
    /usr/data/klipper \
    /usr/data/Klipper \
    /usr/data/kalico \
    /usr/data/Kalico \
    /root/klipper \
    /root/Klipper \
    /root/kalico \
    /root/Kalico \
    /opt/klipper \
    /opt/kalico \
    /usr/local/klipper \
    /usr/local/kalico \
    /usr/share/klipper
  do
    if [ -d "$candidate/klippy/extras" ]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate=$(
    find /usr/data /root /opt /usr/local /usr/share -maxdepth 6 \
      -type d -path '*/klippy/extras' 2>/dev/null | sort | head -n1 || true
  )
  [ -n "$candidate" ] && printf '%s' "${candidate%/klippy/extras}"
}

download_gcode_shell_command() {
  output_path="$1"
  python3 - "$GCODE_SHELL_COMMAND_URL" "$output_path" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
output_path = sys.argv[2]
request = urllib.request.Request(url, headers={"User-Agent": "KlippyAI installer"})
with urllib.request.urlopen(request, timeout=30) as response:
    data = response.read()
text = data.decode("utf-8")
if "RUN_SHELL_COMMAND" not in text or "def load_config_prefix" not in text:
    raise SystemExit("downloaded file does not look like gcode_shell_command.py")
with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(text)
PY
}

install_gcode_shell_command_support() {
  [ -n "$KLIPPER_CHECKOUT" ] || die "Klipper/Kalico checkout could not be detected. Pass --klipper-checkout."
  extras_dir="$KLIPPER_CHECKOUT/klippy/extras"
  target_path="$extras_dir/gcode_shell_command.py"
  [ -d "$extras_dir" ] || die "Klipper extras directory not found: $extras_dir"
  if [ -f "$target_path" ]; then
    log "gcode_shell_command.py is already installed at $target_path"
    return
  fi

  tmp=$(mktemp)
  download_gcode_shell_command "$tmp"
  owner=$(stat -c '%u' "$extras_dir")
  group=$(stat -c '%g' "$extras_dir")
  run_root install -o "$owner" -g "$group" -m 644 "$tmp" "$target_path"
  rm -f "$tmp"
  log "Installed gcode_shell_command.py to $target_path"
}

normalize_service_name() {
  value="$1"
  case "$value" in
    *.service)
      printf '%s' "$value"
      ;;
    *)
      printf '%s.service' "$value"
      ;;
  esac
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE="/etc/klippyai/klippyai.env"
GCODE_SHELL_COMMAND_URL="https://raw.githubusercontent.com/dw-0/kiauh/master/kiauh/extensions/gcode_shell_cmd/assets/gcode_shell_command.py"
INSTALL_USER=$(extract_env_value "$ENV_FILE" "KLIPPYAI_SERVICE_USER" 2>/dev/null || id -un)
if [ -d /usr/data/printer_data/config ]; then
  CONFIG_DIR="/usr/data/printer_data/config"
else
  CONFIG_DIR="$HOME/printer_data/config"
fi
ROOT_CONFIG=""
KLIPPER_CHECKOUT=""
INSTALL_GCODE_SHELL_COMMAND=0
KLIPPYAI_SERVICE="klippyai-agent"
KLIPPER_SERVICE="klipper.service"
RESTART_KLIPPER=0
UPDATE_RUNNER_PATH="/usr/local/bin/klippyai-self-update"
UPDATE_SUDOERS_PATH="/etc/sudoers.d/klippyai-self-update"

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --install-user)
      INSTALL_USER="$2"
      shift 2
      ;;
    --config-dir)
      CONFIG_DIR="$2"
      shift 2
      ;;
    --root-config)
      ROOT_CONFIG="$2"
      shift 2
      ;;
    --klipper-checkout)
      KLIPPER_CHECKOUT="$2"
      shift 2
      ;;
    --install-gcode-shell-command)
      INSTALL_GCODE_SHELL_COMMAND=1
      shift
      ;;
    --klippyai-service)
      KLIPPYAI_SERVICE="$2"
      shift 2
      ;;
    --klipper-service)
      KLIPPER_SERVICE="$2"
      shift 2
      ;;
    --restart-klipper)
      RESTART_KLIPPER=1
      shift
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

[ -n "$ROOT_CONFIG" ] || ROOT_CONFIG="${CONFIG_DIR%/}/printer.cfg"
[ -n "$KLIPPER_CHECKOUT" ] || KLIPPER_CHECKOUT=$(detect_klipper_checkout || true)
MANAGED_CONFIG_DIR="${CONFIG_DIR%/}/klippyai"
UPDATE_MACRO_CFG_PATH="$MANAGED_CONFIG_DIR/klippyai-macros.cfg"
KLIPPER_SERVICE_UNIT=$(normalize_service_name "$KLIPPER_SERVICE")

[ -f "$INSTALL_DIR/pyproject.toml" ] || die "No pyproject.toml found in $INSTALL_DIR"
[ -x "$INSTALL_DIR/.venv/bin/python" ] || die "Virtual environment missing: $INSTALL_DIR/.venv/bin/python"
[ -d "$CONFIG_DIR" ] || die "Klipper config directory not found: $CONFIG_DIR"
[ -f "$ROOT_CONFIG" ] || die "Root printer config not found: $ROOT_CONFIG"
if ! has_gcode_shell_command_support; then
  if [ "$INSTALL_GCODE_SHELL_COMMAND" -eq 1 ]; then
    install_gcode_shell_command_support
  else
    die "gcode_shell_command.py was not found. Rerun with --install-gcode-shell-command to install it first."
  fi
fi

KLIPPER_USER=$(systemctl show -p User --value "$KLIPPER_SERVICE_UNIT" 2>/dev/null || true)
[ -n "$KLIPPER_USER" ] || KLIPPER_USER="root"

MACRO_COMMAND="$UPDATE_RUNNER_PATH"
USES_SUDO=0
if [ "$KLIPPER_USER" != "root" ]; then
  command -v sudo >/dev/null 2>&1 || die "Klipper runs as $KLIPPER_USER but sudo is not installed."
  MACRO_COMMAND="sudo -n $UPDATE_RUNNER_PATH"
  USES_SUDO=1
fi

RUNNER_TMP=$(mktemp)
MACRO_TMP=$(mktemp)
SUDOERS_TMP=$(mktemp)
cleanup() {
  rm -f "$RUNNER_TMP" "$MACRO_TMP" "$SUDOERS_TMP"
}
trap cleanup EXIT

cat >"$RUNNER_TMP" <<EOF
#!/bin/sh

set -eu

INSTALL_USER="$INSTALL_USER"
INSTALL_DIR="$INSTALL_DIR"
SERVICE_NAME="$KLIPPYAI_SERVICE"

run_as_install_user() {
  if [ "\$(id -un)" = "\$INSTALL_USER" ]; then
    "\$@"
    return
  fi

  if command -v runuser >/dev/null 2>&1; then
    runuser -u "\$INSTALL_USER" -- "\$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo -u "\$INSTALL_USER" -H "\$@"
    return
  fi

  printf 'KlippyAI update helper cannot switch to %s\\n' "\$INSTALL_USER" >&2
  exit 1
}

[ -d "\$INSTALL_DIR/.git" ] || {
  printf 'KlippyAI checkout is no longer a git repository: %s\\n' "\$INSTALL_DIR" >&2
  exit 1
}
[ -x "\$INSTALL_DIR/.venv/bin/python" ] || {
  printf 'KlippyAI virtual environment is missing: %s/.venv/bin/python\\n' "\$INSTALL_DIR" >&2
  exit 1
}

run_as_install_user git -C "\$INSTALL_DIR" pull --ff-only
run_as_install_user env SKIP_CYTHON=1 MARKUPSAFE_SKIP_SPEEDUPS=1 "\$INSTALL_DIR/.venv/bin/python" -m pip install --prefer-binary -e "\$INSTALL_DIR"
systemctl restart "\$SERVICE_NAME"
printf 'KlippyAI updated and %s restarted.\\n' "\$SERVICE_NAME"
EOF

cat >"$MACRO_TMP" <<EOF
# KlippyAI self-update shell command
#
# Generated by install-update-macro.sh.

[gcode_shell_command klippyai_update]
command: $MACRO_COMMAND
timeout: 600.
verbose: True

[gcode_macro UPDATE_KLIPPYAI]
description: Pull the latest KlippyAI changes and restart klippyai-agent
gcode:
    RUN_SHELL_COMMAND CMD=klippyai_update
EOF

run_root install -m 755 "$RUNNER_TMP" "$UPDATE_RUNNER_PATH"
run_root install -d -m 755 "$MANAGED_CONFIG_DIR"
run_root install -m 664 "$MACRO_TMP" "$UPDATE_MACRO_CFG_PATH"

if [ "$USES_SUDO" -eq 1 ]; then
  {
    printf '%s ALL=(root) NOPASSWD: %s\n' "$KLIPPER_USER" "$UPDATE_RUNNER_PATH"
    if [ "$INSTALL_USER" != "$KLIPPER_USER" ]; then
      printf '%s ALL=(root) NOPASSWD: %s\n' "$INSTALL_USER" "$UPDATE_RUNNER_PATH"
    fi
  } >"$SUDOERS_TMP"
  if command -v visudo >/dev/null 2>&1; then
    run_root visudo -cf "$SUDOERS_TMP" >/dev/null
  else
    log "visudo is not installed; skipping sudoers syntax validation."
  fi
  run_root install -m 440 "$SUDOERS_TMP" "$UPDATE_SUDOERS_PATH"
else
  log "Klipper runs as root; sudoers file is not needed."
fi

INCLUDE_LINE="[include klippyai/klippyai-macros.cfg]"
if ! grep -Fqx "$INCLUDE_LINE" "$ROOT_CONFIG"; then
  printf '\n%s\n' "$INCLUDE_LINE" | run_root tee -a "$ROOT_CONFIG" >/dev/null
fi

if [ "$RESTART_KLIPPER" -eq 1 ]; then
  run_root systemctl restart "$KLIPPER_SERVICE_UNIT"
fi

log "Installed $UPDATE_RUNNER_PATH"
log "Installed $UPDATE_MACRO_CFG_PATH"
log "Included macro from $ROOT_CONFIG"
log "Macro command: $MACRO_COMMAND"
if [ "$RESTART_KLIPPER" -eq 0 ]; then
  log "Restart Klipper to load UPDATE_KLIPPYAI: systemctl restart $KLIPPER_SERVICE_UNIT"
fi
