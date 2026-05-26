#!/bin/sh

if [ -z "${KLIPPYAI_INSTALL_BASH_REEXEC:-}" ]; then
  if command -v bash >/dev/null 2>&1; then
    KLIPPYAI_INSTALL_BASH_REEXEC=1
    export KLIPPYAI_INSTALL_BASH_REEXEC
    exec bash "$0" "$@"
  fi

  if command -v apt-get >/dev/null 2>&1; then
    bash_install_hint='apt-get update && apt-get install -y bash'
  elif command -v opkg >/dev/null 2>&1; then
    bash_install_hint='opkg update && opkg install bash'
  elif command -v apk >/dev/null 2>&1; then
    bash_install_hint='apk add bash'
  else
    bash_install_hint='no supported package manager was found; install Bash manually or use a normal Klipper host'
  fi

  printf '%s\n' \
    '[KlippyAI] error: this installer requires Bash, but bash was not found.' \
    '[KlippyAI] Install Bash on the printer host, then rerun:' \
    '[KlippyAI]   chmod +x install.sh' \
    '[KlippyAI]   ./install.sh' \
    '[KlippyAI]' \
    '[KlippyAI] Suggested Bash install command for this host:' \
    "[KlippyAI]   $bash_install_hint" \
    '[KlippyAI]' \
    '[KlippyAI] BusyBox/OpenWrt-style images may not provide apt or systemd.' \
    '[KlippyAI] This installer expects a normal Klipper host with Bash, Python 3.10+, systemd, and nginx.' >&2
  exit 127
fi

set -euo pipefail

PROJECT_NAME="KlippyAI"
SERVICE_NAME="klippyai-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
MIN_PYTHON_VERSION="3.10"
PYTHON_BIN=""
PYTHON_VENV_MODULE=""

log() {
  printf '[%s] %s\n' "$PROJECT_NAME" "$*"
}

warn() {
  printf '[%s] warning: %s\n' "$PROJECT_NAME" "$*" >&2
}

die() {
  printf '[%s] error: %s\n' "$PROJECT_NAME" "$*" >&2
  exit 1
}

confirm() {
  local prompt="$1"
  local default="${2:-Y}"
  local suffix="[y/N]"
  local reply=""

  if [[ "$default" == "Y" ]]; then
    suffix="[Y/n]"
  fi

  read -r -p "$prompt $suffix " reply
  reply="${reply:-$default}"
  case "${reply,,}" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
    *) warn "Please answer yes or no."; confirm "$prompt" "$default"; return $? ;;
  esac
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local reply=""
  read -r -p "$prompt [$default]: " reply
  printf '%s' "${reply:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local reply=""
  read -r -s -p "$prompt: " reply
  printf '\n' >&2
  printf '%s' "$reply"
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "This installer only supports Linux hosts."
}

require_cmd() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "Required command not found: $command_name"
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die "sudo is required for installation."
    sudo "$@"
  fi
}

run_as_user() {
  if [[ "$(id -un)" == "$INSTALL_USER" ]]; then
    "$@"
    return
  fi

  if [[ "${EUID}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$INSTALL_USER" -- "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$INSTALL_USER" -H "$@"
    return
  fi

  die "Unable to switch to user '$INSTALL_USER'."
}

backup_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root cp "$path" "${path}.bak.${TIMESTAMP}"
    log "Backed up $path to ${path}.bak.${TIMESTAMP}"
  fi
}

escape_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

ensure_no_spaces() {
  local value="$1"
  local label="$2"
  if [[ "$value" =~ [[:space:]] ]]; then
    die "$label must not contain whitespace."
  fi
}

normalize_root_path() {
  local value="$1"
  value="/${value#/}"
  value="${value%/}"
  if [[ -z "$value" ]]; then
    value="/klippyai"
  fi
  printf '%s' "$value"
}

ensure_numeric_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "Port must be numeric."
  if (( value < 1 || value > 65535 )); then
    die "Port must be between 1 and 65535."
  fi
}

python_version_string() {
  local python_bin="$1"
  "$python_bin" -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))'
}

python_is_supported() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

detect_python_interpreter() {
  local candidate=""

  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    die "KlippyAI requires Python ${MIN_PYTHON_VERSION}+ but python3 is $(python_version_string python3). Install Python ${MIN_PYTHON_VERSION}+ and the matching venv module, or run ./deployment/python/install-python310.sh, then rerun."
  fi

  die "KlippyAI requires Python ${MIN_PYTHON_VERSION}+. Install it manually or run ./deployment/python/install-python310.sh."
}

python_venv_package_name() {
  local python_bin="$1"
  case "$python_bin" in
    python3.[0-9]|python3.[0-9][0-9])
      printf '%s-venv' "$python_bin"
      ;;
    *)
      printf '%s' "python3-venv"
      ;;
  esac
}

have_python_command() {
  local candidate=""

  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      return 0
    fi
  done

  return 1
}

maybe_install_python_packages() {
  if have_python_command; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if confirm "No Python 3 interpreter was found. Install the distro default python3, python3-venv, and python3-pip packages with apt? KlippyAI will verify that the version is ${MIN_PYTHON_VERSION}+." "Y"; then
      run_root apt-get update
      run_root apt-get install -y python3 python3-venv python3-pip
      return
    fi
  fi

  die "Python ${MIN_PYTHON_VERSION}+ is required."
}

ensure_python_venv() {
  local venv_package=""

  if run_as_user "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    PYTHON_VENV_MODULE="venv"
    return
  fi

  if run_as_user "$PYTHON_BIN" -m virtualenv --help >/dev/null 2>&1; then
    PYTHON_VENV_MODULE="virtualenv"
    return
  fi

  venv_package="$(python_venv_package_name "$PYTHON_BIN")"
  if command -v apt-get >/dev/null 2>&1; then
    if confirm "Python venv support is missing for $PYTHON_BIN. Install $venv_package with apt?" "Y"; then
      run_root apt-get update
      run_root apt-get install -y "$venv_package"
      if run_as_user "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
        PYTHON_VENV_MODULE="venv"
        return
      fi
    fi
  fi

  if run_as_user "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    if confirm "Python venv support is missing for $PYTHON_BIN. Install virtualenv with pip and use that to create .venv?" "Y"; then
      run_as_user "$PYTHON_BIN" -m pip install --user virtualenv
      if run_as_user "$PYTHON_BIN" -m virtualenv --help >/dev/null 2>&1; then
        PYTHON_VENV_MODULE="virtualenv"
        return
      fi
    fi
  fi

  die "Python venv support is required for $PYTHON_BIN. Install the distro venv package, or install virtualenv with: $PYTHON_BIN -m pip install --user virtualenv"
}

create_python_virtual_environment() {
  case "$PYTHON_VENV_MODULE" in
    venv)
      run_as_user "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
      ;;
    virtualenv)
      run_as_user "$PYTHON_BIN" -m virtualenv "$INSTALL_DIR/.venv"
      ;;
    *)
      die "No Python virtual environment creator was selected."
      ;;
  esac
}

file_has_trimmed_line() {
  local path="$1"
  local needle="$2"
  [[ -f "$path" ]] || return 1
  awk -v needle="$needle" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) == needle) {
        found = 1
        exit
      }
    }
    END {
      exit(found ? 0 : 1)
    }
  ' "$path"
}

remove_line_from_file_if_present() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! file_has_trimmed_line "$path" "$line_to_remove"; then
    return 0
  fi

  local temp_file
  temp_file="$(mktemp)"
  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  awk -v needle="$line_to_remove" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) != needle) {
        print $0
      }
    }
  ' "$path" >"$temp_file"
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

retire_legacy_file_if_present() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  backup_file "$path"
  run_root rm -f -- "$path"
  log "Removed legacy file $path"
}

detect_default_install_user() {
  if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    printf '%s' "${SUDO_USER}"
    return
  fi

  local current_user
  current_user="$(id -un)"
  if [[ "$current_user" != "root" ]]; then
    printf '%s' "$current_user"
    return
  fi

  if id pi >/dev/null 2>&1; then
    printf '%s' "pi"
    return
  fi

  printf '%s' "root"
}

home_for_user() {
  local user="$1"
  if command -v getent >/dev/null 2>&1; then
    getent passwd "$user" | awk -F: '{ print $6; exit }'
    return
  fi

  awk -F: -v user="$user" '
    $1 == user {
      print $6
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/passwd
}

group_for_user() {
  local user="$1"
  local gid=""

  if id -gn "$user" >/dev/null 2>&1; then
    id -gn "$user"
    return
  fi

  if command -v getent >/dev/null 2>&1; then
    gid="$(getent passwd "$user" | awk -F: '{ print $4; exit }')" || return 1
    getent group "$gid" | awk -F: '{ print $1; exit }' || printf '%s' "$gid"
    return
  fi

  gid="$(awk -F: -v user="$user" '
    $1 == user {
      print $4
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/passwd)" || return 1

  awk -F: -v gid="$gid" '
    $3 == gid {
      print $1
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/group 2>/dev/null || printf '%s' "$gid"
}

detect_moonraker_config_path() {
  local home_dir="$1"
  local config_dir="$2"
  local candidate=""

  for candidate in \
    "$config_dir/moonraker.conf" \
    /usr/data/printer_data/config/moonraker.conf \
    "$home_dir/printer_data/config/moonraker.conf" \
    "$home_dir/moonraker.conf"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  printf '%s' "$config_dir/moonraker.conf"
}

detect_nginx_server_block_path() {
  local candidate=""

  for candidate in \
    /usr/data/nginx/conf.d/mainsail.conf \
    /usr/data/nginx/conf.d/default.conf \
    /usr/data/nginx/nginx.conf \
    /usr/data/nginx/conf/nginx.conf \
    /etc/nginx/conf.d/mainsail.conf \
    /etc/nginx/sites-enabled/mainsail \
    /etc/nginx/sites-available/mainsail
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(
    find /usr/data/nginx -maxdepth 3 -type f \
      \( -name '*.conf' -o -name 'nginx.conf' \) \
      -exec grep -l '^[[:space:]]*server[[:space:]]*{' {} \; 2>/dev/null \
      | sort \
      | head -n1 \
      || true
  )"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return
  fi

  printf '%s' "/etc/nginx/conf.d/mainsail.conf"
}

detect_printer_data_root() {
  local home_dir="$1"
  local candidate=""

  for candidate in \
    /usr/data/printer_data \
    /usr/data/printer_1_data \
    /usr/data/printer_2_data \
    /usr/data/printer_3_data \
    "$home_dir/printer_data" \
    "$home_dir/printer_1_data" \
    "$home_dir/printer_2_data" \
    "$home_dir/printer_3_data"
  do
    if [[ -d "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(find "$home_dir" -maxdepth 1 -type d -name 'printer*_data' 2>/dev/null | sort | head -n1 || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return
  fi

  printf '%s' "$home_dir/printer_data"
}

expand_user_path() {
  local value="$1"
  local home_dir="$2"

  case "$value" in
    "~")
      printf '%s' "$home_dir"
      ;;
    "~/"*)
      printf '%s/%s' "$home_dir" "${value#~/}"
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

extract_update_manager_path() {
  local config_path="$1"
  local home_dir="$2"
  local section_regex="$3"
  local raw_value=""

  [[ -f "$config_path" ]] || return 1
  raw_value="$(awk -v section_regex="$section_regex" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    function strip_comments(value) {
      sub(/[ \t]+#.*/, "", value)
      sub(/^#.*/, "", value)
      return value
    }
    {
      line = $0
      if (line ~ /^[[:space:]]*\[[^]]+\][[:space:]]*$/) {
        gsub(/^[[:space:]]*\[/, "", line)
        gsub(/\][[:space:]]*$/, "", line)
        section = tolower(trim(line))
        in_section = (section ~ ("^update_manager[[:space:]]+(" section_regex ")$"))
        next
      }

      if (!in_section) {
        next
      }

      line = trim(strip_comments($0))
      if (line == "") {
        next
      }

      if (line ~ /^path[[:space:]]*[:=][[:space:]]*/) {
        sub(/^path[[:space:]]*[:=][[:space:]]*/, "", line)
        print trim(line)
        exit
      }
    }
  ' "$config_path")"

  raw_value="$(trim_whitespace "$raw_value")"
  raw_value="${raw_value#\"}"
  raw_value="${raw_value%\"}"
  raw_value="${raw_value#\'}"
  raw_value="${raw_value%\'}"
  [[ -n "$raw_value" ]] || return 1
  expand_user_path "$raw_value" "$home_dir"
}

detect_gcode_shell_command_checkout() {
  local moonraker_config_path="$1"
  local home_dir="$2"
  local candidate=""

  candidate="$(extract_update_manager_path "$moonraker_config_path" "$home_dir" "klipper|kalico" || true)"
  if [[ -n "$candidate" ]] && [[ -f "$candidate/klippy/extras/gcode_shell_command.py" ]]; then
    printf '%s' "$candidate"
    return
  fi

  for candidate in \
    "$home_dir/kalico" \
    "$home_dir/Kalico" \
    "$home_dir/klipper" \
    "$home_dir/Klipper"
  do
    if [[ -f "$candidate/klippy/extras/gcode_shell_command.py" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(find "$home_dir" -maxdepth 3 -type f -path '*/klippy/extras/gcode_shell_command.py' 2>/dev/null | sort | head -n1 || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s' "${candidate%/klippy/extras/gcode_shell_command.py}"
  fi
}

detect_octoeverywhere_root() {
  local home_dir="$1"
  local candidate=""

  for candidate in \
    "$home_dir/octoeverywhere" \
    "$home_dir/OctoEverywhere"
  do
    if [[ -f "$candidate/moonraker_octoeverywhere/static/oe-ui.js" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(find "$home_dir" -maxdepth 3 -type f -path '*/moonraker_octoeverywhere/static/oe-ui.js' 2>/dev/null | sort | head -n1 || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s' "${candidate%/moonraker_octoeverywhere/static/oe-ui.js}"
  fi
}

systemd_unit_exists() {
  local unit_name="$1"
  local load_state=""

  load_state="$(systemctl show -p LoadState --value "$unit_name" 2>/dev/null || true)"
  load_state="$(trim_whitespace "$load_state")"
  [[ -n "$load_state" ]] && [[ "$load_state" != "not-found" ]]
}

detect_systemd_unit_user() {
  local unit_name="$1"
  local fallback_user="$2"
  local user_name=""

  if ! systemd_unit_exists "$unit_name"; then
    printf '%s' "$fallback_user"
    return
  fi

  user_name="$(systemctl show -p User --value "$unit_name" 2>/dev/null || true)"
  user_name="$(trim_whitespace "$user_name")"
  printf '%s' "${user_name:-$fallback_user}"
}

detect_octoeverywhere_service_name() {
  local candidate=""

  for candidate in octoeverywhere.service octoeverywhere; do
    if systemd_unit_exists "$candidate"; then
      printf '%s' "${candidate%.service}"
      return
    fi
  done
}

detect_git_origin() {
  if ! command -v git >/dev/null 2>&1; then
    printf '%s' "https://github.com/meltiseugen/KlippyAI.git"
    return
  fi

  local origin=""
  origin="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$origin" ]]; then
    printf '%s' "https://github.com/meltiseugen/KlippyAI.git"
    return
  fi

  case "$origin" in
    git@github.com:*)
      origin="${origin#git@github.com:}"
      printf 'https://github.com/%s' "$origin"
      return
      ;;
    ssh://git@github.com/*)
      origin="${origin#ssh://git@github.com/}"
      printf 'https://github.com/%s' "$origin"
      return
      ;;
  esac

  printf '%s' "$origin"
}

detect_git_primary_branch() {
  if ! command -v git >/dev/null 2>&1; then
    printf '%s' "main"
    return
  fi

  local branch=""
  branch="$(git -C "$INSTALL_DIR" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  branch="${branch#origin/}"
  if [[ -n "$branch" ]]; then
    printf '%s' "$branch"
    return
  fi

  branch="$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -n "$branch" ]] && [[ "$branch" != "HEAD" ]]; then
    printf '%s' "$branch"
    return
  fi

  printf '%s' "main"
}

write_env_file() {
  local temp_file
  temp_file="$(mktemp)"

  {
    printf 'KLIPPYAI_ENVIRONMENT="%s"\n' "$(escape_env_value "production")"
    printf 'KLIPPYAI_CONFIG_FILE="%s"\n' "$(escape_env_value "$KLIPPYAI_CFG_PATH")"
    printf 'KLIPPYAI_SERVICE_USER="%s"\n' "$(escape_env_value "$INSTALL_USER")"
    printf 'KLIPPYAI_PROJECT_CHECKOUT_PATH="%s"\n' "$(escape_env_value "$INSTALL_DIR")"
    printf 'KLIPPYAI_NGINX_SERVER_BLOCK_PATH="%s"\n' "$(escape_env_value "$KLIPPYAI_NGINX_SERVER_BLOCK_PATH")"
    printf 'KLIPPYAI_HOST="%s"\n' "$(escape_env_value "127.0.0.1")"
    printf 'KLIPPYAI_MOONRAKER_URL="%s"\n' "$(escape_env_value "$KLIPPYAI_MOONRAKER_URL")"
    printf 'KLIPPYAI_MANAGED_CONFIG_DIR_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_MANAGED_CONFIG_DIR_NAME")"
    printf 'KLIPPYAI_SESSION_TTL_SECONDS="%s"\n' "$(escape_env_value "3600")"
    printf 'KLIPPYAI_MOONRAKER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_MOONRAKER_SERVICE_NAME")"
    printf 'KLIPPYAI_KLIPPER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_KLIPPER_SERVICE_NAME")"
    printf 'KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="%s"\n' "$(escape_env_value "$KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS")"
    printf 'KLIPPYAI_OPENAI_API_KEY="%s"\n' "$(escape_env_value "$KLIPPYAI_OPENAI_API_KEY")"
  } >"$temp_file"

  run_root install -d -m 755 /etc/klippyai
  backup_file /etc/klippyai/klippyai.env
  run_root install -m 600 "$temp_file" /etc/klippyai/klippyai.env
  rm -f "$temp_file"
}

write_cfg_file() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KlippyAI runtime configuration
#
# This file is intended to be easy to edit from Mainsail.
#
# Notes:
# - Restart klippyai-agent after editing this file.
# - Hidden install metadata is stored in /etc/klippyai/klippyai.env.
# - Keep API keys in /etc/klippyai/klippyai.env, not in this file.

[install]
printer_data_root: $KLIPPYAI_PRINTER_DATA_ROOT  # Printer data root. Example: /home/biqu/printer_data
mainsail_config_dir: $KLIPPYAI_MAINSAIL_CONFIG_DIR  # Config dir that contains the managed klippyai/ folder. Example: /home/biqu/printer_data/config

[printer_identity]
firmware_flavor:  # Main firmware flavor. Examples: Kalico, Klipper
firmware_version:  # Firmware version string. Examples: v2026.05.00-4, v0.13.0-221
host_model:  # Host computer / SBC model. Examples: BigTreeTech CB1, Raspberry Pi 4 Model B
host_distribution:  # Linux distribution on the host. Examples: Debian GNU/Linux 11 (bullseye) 11, Armbian 24.2 Bookworm
mainboard:  # Printer controller board model. Examples: BTT Manta E3EZ, BTT Octopus Pro
toolhead:  # Toolhead board / electronics model. Examples: BTT EBB36, FYSETC H36 Combo, Orbiter Nitehawk

[printer_capabilities]
probe_type: none  # Probe family. Examples: none, bltouch, beacon, eddy
accelerometer: none  # Accelerometer family. Examples: none, adxl345, lis2dw
filament_sensor: none  # Filament sensor family. Examples: none, switch, motion
bed_mesh_configured: false  # Whether bed mesh is configured. Examples: true, false
input_shaper_configured: false  # Whether input shaper is configured. Examples: true, false
canbus_enabled: false  # Whether the printer uses CAN anywhere. Examples: true, false
addons:  # Comma-separated addons. Examples: OctoEverywhere, KAMP, KlipperScreen

[config_context]
root_config_file:  # Root Klipper config entry point. Examples: printer.cfg, machines/voron/printer-main.cfg
ignore_globs:  # Comma-separated exclude globs. Examples: backups/**, archive/**, timelapse/**

[server]
port: $KLIPPYAI_PORT  # Local agent port. Examples: 8811, 9911
root_path: $KLIPPYAI_ROOT_PATH  # Public reverse-proxy path. Examples: /klippyai, /ai
data_dir: $KLIPPYAI_DATA_DIR  # Local runtime data directory. Examples: /var/lib/klippyai, /srv/klippyai/data
checkpoint_db: $KLIPPYAI_CHECKPOINT_DB  # SQLite checkpoint DB path. Examples: /var/lib/klippyai/checkpoints.sqlite, /srv/klippyai/checkpoints.sqlite
enable_write_actions: $KLIPPYAI_ENABLE_WRITE_ACTIONS  # Reserved for future write actions. Keep this false.

[llm]
llm_provider: $KLIPPYAI_LLM_PROVIDER  # Chat backend provider. Examples: stub, openai
openai_model: $KLIPPYAI_OPENAI_MODEL  # OpenAI model when provider = openai. Examples: gpt-5.4-mini, gpt-5.5

[logs]
collect_host_logs: $KLIPPYAI_COLLECT_HOST_LOGS  # Whether to collect host logs. Examples: true, false
logs_dir_path: $KLIPPYAI_LOGS_DIR_PATH  # Directory that contains Klipper, Moonraker, and KlippyAI logs. Examples: /home/biqu/printer_data/logs, /srv/printer_data/logs
agent_log_file_name: $KLIPPYAI_AGENT_LOG_FILE_NAME  # KlippyAI runtime log filename. Examples: klippyai.log, ai-agent.log
agent_log_level: $KLIPPYAI_AGENT_LOG_LEVEL  # Runtime log verbosity. Examples: INFO, DEBUG, WARNING
log_tail_lines_default: $KLIPPYAI_LOG_TAIL_LINES_DEFAULT  # Default tail length when no override exists. Examples: 100, 200
excluded_logs:  # Comma-separated denylist by name, stem, or glob. Examples: klippyai.log, crowsnest, *_debug.log

[log_tail_lines]
klippy: 100  # Tail lines for klippy.log
moonraker: 200  # Tail lines for moonraker.log
klippyai: 100  # Tail lines for klippyai.log

[system]
collect_systemd_diagnostics: $KLIPPYAI_COLLECT_SYSTEMD_DIAGNOSTICS  # Whether to collect systemctl and journal diagnostics. Examples: true, false
journal_lines: $KLIPPYAI_JOURNAL_LINES  # Journal lines to include per service. Examples: 100, 200, 400
EOF

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KLIPPYAI_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPYAI_CFG_PATH"
  rm -f "$temp_file"
}

write_moonraker_extension_cfg() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KlippyAI Moonraker integration
#
# This file is included from moonraker.conf so that KlippyAI appears in
# Moonraker's update manager and can be managed from Mainsail.

[update_manager klippyai-agent]
type: git_repo
channel: dev
path: $INSTALL_DIR
origin: $KLIPPYAI_GIT_ORIGIN
primary_branch: $KLIPPYAI_GIT_PRIMARY_BRANCH
managed_services: klippyai-agent
info_tags:
    desc=KlippyAI
EOF

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH"
  rm -f "$temp_file"
}

read_ini_value() {
  local path="$1"
  local target_section="$2"
  local target_key="$3"

  [[ -f "$path" ]] || return 1
  awk -v target_section="${target_section,,}" -v target_key="${target_key,,}" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      line = $0
      if (line ~ /^[[:space:]]*\[[^]]+\][[:space:]]*$/) {
        gsub(/^[[:space:]]*\[/, "", line)
        gsub(/\][[:space:]]*$/, "", line)
        current_section = tolower(trim(line))
        next
      }

      if (current_section != target_section) {
        next
      }

      line = $0
      sub(/[ \t]+#.*/, "", line)
      line = trim(line)
      if (line == "") {
        next
      }

      if (line ~ /^[A-Za-z0-9_]+[[:space:]]*[:=][[:space:]]*/) {
        key = line
        sub(/[[:space:]]*[:=].*$/, "", key)
        key = tolower(trim(key))
        if (key == target_key) {
          sub(/^[A-Za-z0-9_]+[[:space:]]*[:=][[:space:]]*/, "", line)
          print trim(line)
          exit
        }
      }
    }
  ' "$path"
}

resolve_klipper_root_config_path() {
  local root_value=""

  root_value="$(read_ini_value "$KLIPPYAI_CFG_PATH" "config_context" "root_config_file" || true)"
  root_value="$(trim_whitespace "$root_value")"
  root_value="${root_value#\"}"
  root_value="${root_value%\"}"
  root_value="${root_value#\'}"
  root_value="${root_value%\'}"
  if [[ -z "$root_value" ]]; then
    printf '%s' "$KLIPPYAI_MAINSAIL_CONFIG_DIR/printer.cfg"
    return
  fi

  if [[ "$root_value" == /* ]]; then
    printf '%s' "$root_value"
    return
  fi

  printf '%s/%s' "$KLIPPYAI_MAINSAIL_CONFIG_DIR" "$root_value"
}

relative_config_include_path() {
  local target_path="$1"
  local source_config_path="$2"

  python3 - "$target_path" "${source_config_path%/*}" <<'PY'
import os
import sys

target = os.path.abspath(sys.argv[1])
source_dir = os.path.abspath(sys.argv[2])
print(os.path.relpath(target, source_dir).replace(os.sep, "/"))
PY
}

build_include_line() {
  local target_path="$1"
  local source_config_path="$2"
  printf '[include %s]' "$(relative_config_include_path "$target_path" "$source_config_path")"
}

ensure_moonraker_include() {
  local include_line
  include_line="$(build_include_line "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH" "$KLIPPYAI_MOONRAKER_CONFIG_PATH")"
  local legacy_include_line="[include $(basename "$KLIPPYAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH")]"

  [[ -f "$KLIPPYAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KLIPPYAI_MOONRAKER_CONFIG_PATH"
  if [[ "$legacy_include_line" != "$include_line" ]]; then
    remove_line_from_file_if_present "$KLIPPYAI_MOONRAKER_CONFIG_PATH" "$legacy_include_line"
  fi
  if grep -Fqx "$include_line" "$KLIPPYAI_MOONRAKER_CONFIG_PATH"; then
    return
  fi

  backup_file "$KLIPPYAI_MOONRAKER_CONFIG_PATH"
  printf '\n%s\n' "$include_line" | run_root tee -a "$KLIPPYAI_MOONRAKER_CONFIG_PATH" >/dev/null
}

ensure_generic_include() {
  local target_path="$1"
  local include_line="$2"

  [[ -f "$target_path" ]] || die "Config file not found: $target_path"
  if file_has_trimmed_line "$target_path" "$include_line"; then
    return
  fi

  backup_file "$target_path"
  printf '\n%s\n' "$include_line" | run_root tee -a "$target_path" >/dev/null
}

ensure_moonraker_allowed_service() {
  if [[ -f "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]] && grep -Fqx "$SERVICE_NAME" "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH"; then
    return
  fi

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPYAI_PRINTER_DATA_ROOT"
  if [[ -f "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]]; then
    backup_file "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH"
    printf '%s\n' "$SERVICE_NAME" | run_root tee -a "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH" >/dev/null
    return
  fi

  local temp_file
  temp_file="$(mktemp)"
  printf '%s\n' "$SERVICE_NAME" >"$temp_file"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH"
  rm -f "$temp_file"
}

write_systemd_service() {
  local temp_file
  local unit_dir="/etc/systemd/system"
  local unit_path="$unit_dir/${SERVICE_NAME}.service"
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
[Unit]
Description=KlippyAI agent
After=network-online.target moonraker.service
Wants=network-online.target

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=-/etc/klippyai/klippyai.env
ExecStart=$INSTALL_DIR/.venv/bin/klippyai-agent
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

  run_root install -d -m 755 "$unit_dir"
  backup_file "$unit_path"
  run_root install -m 644 "$temp_file" "$unit_path"
  rm -f "$temp_file"
}

write_nginx_snippet() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
location ${KLIPPYAI_ROOT_PATH}/ {
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_pass http://127.0.0.1:${KLIPPYAI_PORT}/;
}
EOF

  backup_file /etc/klippyai/nginx-location.conf
  run_root install -m 644 "$temp_file" /etc/klippyai/nginx-location.conf
  rm -f "$temp_file"
}

write_update_runner_script() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
#!/bin/sh

set -eu

INSTALL_USER="$INSTALL_USER"
INSTALL_DIR="$INSTALL_DIR"
SERVICE_NAME="$SERVICE_NAME"

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

  backup_file "$KLIPPYAI_UPDATE_RUNNER_PATH"
  run_root install -m 755 "$temp_file" "$KLIPPYAI_UPDATE_RUNNER_PATH"
  rm -f "$temp_file"
}

write_update_sudoers_file() {
  local temp_file
  temp_file="$(mktemp)"

  {
    printf '%s ALL=(root) NOPASSWD: %s\n' "$KLIPPYAI_KLIPPER_SYSTEM_USER" "$KLIPPYAI_UPDATE_RUNNER_PATH"
    if [[ "$INSTALL_USER" != "$KLIPPYAI_KLIPPER_SYSTEM_USER" ]]; then
      printf '%s ALL=(root) NOPASSWD: %s\n' "$INSTALL_USER" "$KLIPPYAI_UPDATE_RUNNER_PATH"
    fi
  } >"$temp_file"

  if command -v visudo >/dev/null 2>&1; then
    run_root visudo -cf "$temp_file" >/dev/null
  else
    warn "visudo is not installed; skipping sudoers syntax validation for $KLIPPYAI_UPDATE_SUDOERS_PATH."
  fi

  backup_file "$KLIPPYAI_UPDATE_SUDOERS_PATH"
  run_root install -m 440 "$temp_file" "$KLIPPYAI_UPDATE_SUDOERS_PATH"
  rm -f "$temp_file"
}

write_update_macro_cfg() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KlippyAI self-update shell command
#
# Generated by install.sh. The UPDATE_KLIPPYAI macro pulls the latest KlippyAI
# checkout, refreshes the editable install inside the virtual environment, and
# restarts the klippyai-agent systemd service.

[gcode_shell_command klippyai_update]
command: sudo -n $KLIPPYAI_UPDATE_RUNNER_PATH
timeout: 600.
verbose: True

[gcode_macro UPDATE_KLIPPYAI]
description: Pull the latest KlippyAI changes and restart klippyai-agent
gcode:
    RUN_SHELL_COMMAND CMD=klippyai_update
EOF

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KLIPPYAI_UPDATE_MACRO_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPYAI_UPDATE_MACRO_CFG_PATH"
  rm -f "$temp_file"
}

install_update_macro_integration() {
  KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH="$(resolve_klipper_root_config_path)"
  if [[ ! -f "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH" ]]; then
    warn "Skipping UPDATE_KLIPPYAI macro because the detected Klipper root config was not found: $KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH"
    INSTALL_UPDATE_MACRO="skipped"
    return
  fi

  write_update_runner_script
  write_update_sudoers_file
  write_update_macro_cfg
  if [[ "$KLIPPYAI_LEGACY_UPDATE_MACRO_CFG_PATH" != "$KLIPPYAI_UPDATE_MACRO_CFG_PATH" ]]; then
    remove_line_from_file_if_present "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH" "[include $(basename "$KLIPPYAI_LEGACY_UPDATE_MACRO_CFG_PATH")]"
    retire_legacy_file_if_present "$KLIPPYAI_LEGACY_UPDATE_MACRO_CFG_PATH"
  fi
  ensure_generic_include \
    "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH" \
    "$(build_include_line "$KLIPPYAI_UPDATE_MACRO_CFG_PATH" "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH")"
}

ensure_nginx_include() {
  local include_line="include /etc/klippyai/nginx-location.conf;"
  local path="$KLIPPYAI_NGINX_SERVER_BLOCK_PATH"

  [[ -n "$path" ]] || die "nginx server block path is not set."
  [[ -f "$path" ]] || die "nginx server block file not found: $path"
  if file_has_trimmed_line "$path" "$include_line"; then
    return
  fi

  local temp_file
  temp_file="$(mktemp)"
  if ! awk -v include_line="$include_line" '
    function strip_comments(value) {
      sub(/#.*/, "", value)
      return value
    }
    function count_char(value, char,    i, total) {
      total = 0
      for (i = 1; i <= length(value); i++) {
        if (substr(value, i, 1) == char) {
          total++
        }
      }
      return total
    }
    {
      raw = $0
      line = strip_comments($0)

      if (!in_server) {
        if (line ~ /^[[:space:]]*server[[:space:]]*\{/) {
          in_server = 1
          depth = count_char(line, "{") - count_char(line, "}")
          print raw
          next
        }
        print raw
        next
      }

      next_depth = depth + count_char(line, "{") - count_char(line, "}")
      if (!inserted && depth > 0 && next_depth == 0) {
        print "    " include_line
        inserted = 1
      }
      print raw
      depth = next_depth
    }
    END {
      if (!inserted) {
        exit 1
      }
    }
  ' "$path" >"$temp_file"; then
    rm -f "$temp_file"
    die "Could not find a server block to patch in $path"
  fi

  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

reload_nginx() {
  run_root nginx -t
  run_root systemctl reload nginx
}

install_mainsail_custom_nav() {
  [[ -n "${KLIPPYAI_MAINSAIL_CONFIG_DIR:-}" ]] || die "Mainsail config directory is not set."
  [[ -d "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]] || die "Mainsail config directory does not exist: $KLIPPYAI_MAINSAIL_CONFIG_DIR"

  local href="${KLIPPYAI_ROOT_PATH%/}/"
  run_as_user bash "$INSTALL_DIR/integrations/mainsail/install-custom-nav.sh" \
    --config-dir "$KLIPPYAI_MAINSAIL_CONFIG_DIR" \
    --href "$href" \
    --title "KlippyAI" \
    --target "_blank" \
    --position 85
}

install_octoeverywhere_integration() {
  [[ -n "${KLIPPYAI_OE_ROOT:-}" ]] || die "OctoEverywhere checkout path is not set."
  local script_path="$INSTALL_DIR/integrations/octoeverywhere/apply-local-klippyai-route-patch.sh"
  [[ -f "$script_path" ]] || die "OctoEverywhere integration helper not found: $script_path"

  local cmd=(bash "$script_path" --oe-root "$KLIPPYAI_OE_ROOT" --klippyai-prefix "$KLIPPYAI_ROOT_PATH" --klippyai-port "$KLIPPYAI_PORT" --nav-target "_blank")
  if [[ -n "${KLIPPYAI_OE_SERVICE_NAME:-}" ]]; then
    cmd+=(--restart-service --service "$KLIPPYAI_OE_SERVICE_NAME")
  fi

  "${cmd[@]}"
}

print_summary() {
  cat <<EOF

Install summary
---------------
User:                 $INSTALL_USER
Project checkout:     $INSTALL_DIR
Moonraker URL:        $KLIPPYAI_MOONRAKER_URL
Moonraker config:     $KLIPPYAI_MOONRAKER_CONFIG_PATH
Printer data root:    $KLIPPYAI_PRINTER_DATA_ROOT
Mainsail config dir:  $KLIPPYAI_MAINSAIL_CONFIG_DIR
Managed config dir:   $KLIPPYAI_MANAGED_CONFIG_DIR_PATH
KlippyAI cfg:         $KLIPPYAI_CFG_PATH
Moonraker ext cfg:    $KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH
Provider:             $KLIPPYAI_LLM_PROVIDER
Model:                $KLIPPYAI_OPENAI_MODEL
Root path:            $KLIPPYAI_ROOT_PATH
nginx server block:   $KLIPPYAI_NGINX_SERVER_BLOCK_PATH
Patch nginx include:  $PATCH_NGINX_INCLUDE
Local bind port:      $KLIPPYAI_PORT
Data dir:             $KLIPPYAI_DATA_DIR
Runtime mode:         read-only
KlippyAI log file:    $KLIPPYAI_LOGS_DIR_PATH/$KLIPPYAI_AGENT_LOG_FILE_NAME
Mainsail nav link:    $INSTALL_MAINSAIL_NAV
Update macro:         $INSTALL_UPDATE_MACRO
OctoEverywhere patch: $INSTALL_OCTOEVERYWHERE_PATCH

EOF
}

main() {
  require_linux
  require_cmd awk
  require_cmd find
  require_cmd git
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  require_cmd systemctl

  [[ -f "$SCRIPT_DIR/pyproject.toml" ]] || die "Run this installer from a KlippyAI checkout."

  log "Preparing interactive installation."

  DEFAULT_INSTALL_USER="$(detect_default_install_user)"
  INSTALL_USER="$(prompt_default "Linux user that should run the KlippyAI service" "$DEFAULT_INSTALL_USER")"
  id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist."

  INSTALL_HOME="$(home_for_user "$INSTALL_USER")"
  [[ -n "$INSTALL_HOME" ]] || die "Could not determine the home directory for '$INSTALL_USER'."
  INSTALL_GROUP="$(group_for_user "$INSTALL_USER")"

  STANDARD_INSTALL_DIR="$INSTALL_HOME/KlippyAI"
  INSTALL_DIR="$(prompt_default "Project checkout path to install from" "$STANDARD_INSTALL_DIR")"
  ensure_no_spaces "$INSTALL_DIR" "Project checkout path"
  [[ -f "$INSTALL_DIR/pyproject.toml" ]] || die "No pyproject.toml found in $INSTALL_DIR."
  [[ -e "$INSTALL_DIR/.git" ]] || die "$INSTALL_DIR is not a git checkout. Clone the repository before running install.sh."
  run_as_user test -r "$INSTALL_DIR/pyproject.toml" || die "User '$INSTALL_USER' cannot read $INSTALL_DIR."
  run_as_user test -w "$INSTALL_DIR" || die "User '$INSTALL_USER' must be able to write to $INSTALL_DIR."

  DEFAULT_PRINTER_DATA_ROOT="$(detect_printer_data_root "$INSTALL_HOME")"
  KLIPPYAI_PRINTER_DATA_ROOT="$(prompt_default "Printer data root" "$DEFAULT_PRINTER_DATA_ROOT")"
  ensure_no_spaces "$KLIPPYAI_PRINTER_DATA_ROOT" "Printer data root"
  KLIPPYAI_MAINSAIL_CONFIG_DIR="$(prompt_default "Mainsail config directory" "$KLIPPYAI_PRINTER_DATA_ROOT/config")"
  ensure_no_spaces "$KLIPPYAI_MAINSAIL_CONFIG_DIR" "Mainsail config directory"
  KLIPPYAI_MANAGED_CONFIG_DIR_NAME="klippyai"
  KLIPPYAI_MANAGED_CONFIG_DIR_PATH="$KLIPPYAI_MAINSAIL_CONFIG_DIR/$KLIPPYAI_MANAGED_CONFIG_DIR_NAME"
  KLIPPYAI_CFG_PATH="$KLIPPYAI_MANAGED_CONFIG_DIR_PATH/klippyai.cfg"
  KLIPPYAI_LEGACY_CFG_PATH="$KLIPPYAI_MAINSAIL_CONFIG_DIR/klippyai.cfg"
  KLIPPYAI_MOONRAKER_CONFIG_PATH="$(detect_moonraker_config_path "$INSTALL_HOME" "$KLIPPYAI_MAINSAIL_CONFIG_DIR")"
  [[ -f "$KLIPPYAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KLIPPYAI_MOONRAKER_CONFIG_PATH"
  KLIPPYAI_MOONRAKER_CONFIG_DIR="${KLIPPYAI_MOONRAKER_CONFIG_PATH%/*}"
  KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH="$KLIPPYAI_MANAGED_CONFIG_DIR_PATH/klippyai-moonraker.cfg"
  KLIPPYAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH="$KLIPPYAI_MOONRAKER_CONFIG_DIR/klippyai-moonraker.cfg"
  KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH="$KLIPPYAI_PRINTER_DATA_ROOT/moonraker.asvc"
  KLIPPYAI_GIT_ORIGIN="$(detect_git_origin)"
  KLIPPYAI_GIT_PRIMARY_BRANCH="$(detect_git_primary_branch)"

  KLIPPYAI_MOONRAKER_URL="$(prompt_default "Moonraker URL" "http://127.0.0.1:7125")"
  KLIPPYAI_ROOT_PATH="$(normalize_root_path "$(prompt_default "Reverse-proxy root path" "/klippyai")")"
  KLIPPYAI_PORT="$(prompt_default "Local KlippyAI bind port" "8811")"
  ensure_numeric_port "$KLIPPYAI_PORT"
  KLIPPYAI_DATA_DIR="$(prompt_default "Local KlippyAI data directory" "/var/lib/klippyai")"
  ensure_no_spaces "$KLIPPYAI_DATA_DIR" "Local data directory"
  KLIPPYAI_CHECKPOINT_DB="${KLIPPYAI_DATA_DIR}/checkpoints.sqlite"
  KLIPPYAI_COLLECT_HOST_LOGS="true"
  KLIPPYAI_LOGS_DIR_PATH="${KLIPPYAI_PRINTER_DATA_ROOT}/logs"
  KLIPPYAI_AGENT_LOG_FILE_NAME="klippyai.log"
  KLIPPYAI_AGENT_LOG_LEVEL="INFO"
  KLIPPYAI_LOG_TAIL_LINES_DEFAULT="100"
  KLIPPYAI_COLLECT_SYSTEMD_DIAGNOSTICS="true"
  KLIPPYAI_MOONRAKER_SERVICE_NAME="moonraker.service"
  KLIPPYAI_KLIPPER_SERVICE_NAME="klipper.service"
  KLIPPYAI_JOURNAL_LINES="200"
  KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="6000"
  KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT="16000"
  KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="6"
  KLIPPYAI_GCODE_SHELL_COMMAND_CHECKOUT="$(detect_gcode_shell_command_checkout "$KLIPPYAI_MOONRAKER_CONFIG_PATH" "$INSTALL_HOME" || true)"
  KLIPPYAI_OE_ROOT="$(detect_octoeverywhere_root "$INSTALL_HOME" || true)"
  KLIPPYAI_OE_SERVICE_NAME="$(detect_octoeverywhere_service_name || true)"
  KLIPPYAI_UPDATE_RUNNER_PATH="/usr/local/bin/klippyai-self-update"
  KLIPPYAI_UPDATE_SUDOERS_PATH="/etc/sudoers.d/klippyai-self-update"
  KLIPPYAI_UPDATE_MACRO_CFG_PATH="$KLIPPYAI_MANAGED_CONFIG_DIR_PATH/klippyai-macros.cfg"
  KLIPPYAI_LEGACY_UPDATE_MACRO_CFG_PATH="$KLIPPYAI_MAINSAIL_CONFIG_DIR/klippyai-update-macro.cfg"
  KLIPPYAI_KLIPPER_SYSTEM_USER="$(detect_systemd_unit_user "$KLIPPYAI_KLIPPER_SERVICE_NAME" "$INSTALL_USER")"
  KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH=""
  INSTALL_UPDATE_MACRO="no"
  INSTALL_OCTOEVERYWHERE_PATCH="no"

  KLIPPYAI_LLM_PROVIDER="$(prompt_default "LLM provider (currently: openai or stub)" "openai")"
  KLIPPYAI_LLM_PROVIDER="${KLIPPYAI_LLM_PROVIDER,,}"
  KLIPPYAI_OPENAI_MODEL="$(prompt_default "Model name" "gpt-5.4-mini")"
  KLIPPYAI_OPENAI_API_KEY=""

  case "$KLIPPYAI_LLM_PROVIDER" in
    openai)
      KLIPPYAI_OPENAI_API_KEY="$(prompt_secret "OpenAI API key")"
      if [[ -z "$KLIPPYAI_OPENAI_API_KEY" ]]; then
        die "An OpenAI API key is required when provider is 'openai'."
      fi
      ;;
    stub)
      warn "Using the local stub provider. Diagnostics will be limited to deterministic rules and placeholder responses."
      ;;
    *)
      die "Unsupported provider '$KLIPPYAI_LLM_PROVIDER'. Current installer support is: openai, stub."
      ;;
  esac

  KLIPPYAI_ENABLE_WRITE_ACTIONS="false"

  if confirm "Install a Mainsail custom-navigation link to KlippyAI?" "Y"; then
    INSTALL_MAINSAIL_NAV="yes"
  else
    INSTALL_MAINSAIL_NAV="no"
  fi

  if confirm "Patch the Mainsail nginx server block automatically?" "Y"; then
    PATCH_NGINX_INCLUDE="yes"
    KLIPPYAI_NGINX_SERVER_BLOCK_PATH="$(prompt_default "nginx server block path" "$(detect_nginx_server_block_path)")"
    ensure_no_spaces "$KLIPPYAI_NGINX_SERVER_BLOCK_PATH" "nginx server block path"
    [[ -f "$KLIPPYAI_NGINX_SERVER_BLOCK_PATH" ]] || die "nginx server block file not found: $KLIPPYAI_NGINX_SERVER_BLOCK_PATH"
  else
    PATCH_NGINX_INCLUDE="no"
    KLIPPYAI_NGINX_SERVER_BLOCK_PATH="$(detect_nginx_server_block_path)"
  fi

  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]] && [[ ! -d "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]]; then
    die "Mainsail config directory does not exist: $KLIPPYAI_MAINSAIL_CONFIG_DIR"
  fi

  if [[ -n "$KLIPPYAI_GCODE_SHELL_COMMAND_CHECKOUT" ]]; then
    log "Detected gcode_shell_command support in $KLIPPYAI_GCODE_SHELL_COMMAND_CHECKOUT."
    if confirm "Install an UPDATE_KLIPPYAI macro that pulls the repo and restarts $SERVICE_NAME?" "N"; then
      INSTALL_UPDATE_MACRO="yes"
    fi
  else
    INSTALL_UPDATE_MACRO="unavailable"
  fi

  if [[ -n "$KLIPPYAI_OE_ROOT" ]]; then
    log "Detected OctoEverywhere checkout at $KLIPPYAI_OE_ROOT."
    if confirm "Apply the optional OctoEverywhere /klippyai integration now?" "N"; then
      INSTALL_OCTOEVERYWHERE_PATCH="yes"
    fi
  else
    INSTALL_OCTOEVERYWHERE_PATCH="unavailable"
  fi

  print_summary
  confirm "Proceed with installation?" "Y" || die "Installation cancelled."

  maybe_install_python_packages
  detect_python_interpreter
  ensure_python_venv
  log "Using Python interpreter: $PYTHON_BIN ($(python_version_string "$PYTHON_BIN"))"

  log "Creating service data directory."
  run_root install -d -m 755 "$KLIPPYAI_DATA_DIR"
  run_root chown "$INSTALL_USER:$INSTALL_GROUP" "$KLIPPYAI_DATA_DIR"

  log "Creating Python virtual environment."
  if [[ -d "$INSTALL_DIR/.venv" ]]; then
    if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
      warn "Existing virtual environment at $INSTALL_DIR/.venv is incomplete."
      confirm "Recreate the virtual environment?" "Y" || die "Installation cancelled."
      run_as_user rm -rf "$INSTALL_DIR/.venv"
    elif ! python_is_supported "$INSTALL_DIR/.venv/bin/python"; then
      warn "Existing virtual environment uses Python $(python_version_string "$INSTALL_DIR/.venv/bin/python"), but KlippyAI requires Python ${MIN_PYTHON_VERSION}+."
      confirm "Recreate the virtual environment with $PYTHON_BIN?" "Y" || die "Installation cancelled."
      run_as_user rm -rf "$INSTALL_DIR/.venv"
    fi
  fi
  if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    create_python_virtual_environment
  fi

  log "Installing Python package into the virtual environment."
  run_as_user "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
  run_as_user env SKIP_CYTHON=1 MARKUPSAFE_SKIP_SPEEDUPS=1 "$INSTALL_DIR/.venv/bin/python" -m pip install --prefer-binary -e "$INSTALL_DIR"

  log "Writing /etc/klippyai/klippyai.env"
  write_env_file

  log "Writing ${KLIPPYAI_CFG_PATH}"
  write_cfg_file
  if [[ "$KLIPPYAI_LEGACY_CFG_PATH" != "$KLIPPYAI_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KLIPPYAI_LEGACY_CFG_PATH"
  fi

  log "Detecting printer profile into ${KLIPPYAI_CFG_PATH}"
  if ! run_as_user "$INSTALL_DIR/.venv/bin/klippyai-detect-profile" \
    --config-file "$KLIPPYAI_CFG_PATH" \
    --moonraker-url "$KLIPPYAI_MOONRAKER_URL" \
    --printer-data-root "$KLIPPYAI_PRINTER_DATA_ROOT" \
    --overwrite
  then
    warn "Automatic printer profile detection failed. You can edit the printer profile sections in ${KLIPPYAI_CFG_PATH} later."
  fi

  log "Writing ${KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH}"
  write_moonraker_extension_cfg
  if [[ "$KLIPPYAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH" != "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KLIPPYAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH"
  fi

  log "Adding KlippyAI include to ${KLIPPYAI_MOONRAKER_CONFIG_PATH}"
  ensure_moonraker_include

  log "Allowing Moonraker to manage ${SERVICE_NAME}"
  ensure_moonraker_allowed_service

  log "Writing systemd service."
  write_systemd_service

  log "Generating nginx location snippet."
  write_nginx_snippet

  if [[ "$PATCH_NGINX_INCLUDE" == "yes" ]]; then
    log "Patching nginx server block."
    ensure_nginx_include
    log "Testing and reloading nginx."
    if ! reload_nginx; then
      if [[ -f "${KLIPPYAI_NGINX_SERVER_BLOCK_PATH}.bak.${TIMESTAMP}" ]]; then
        warn "nginx validation failed after patching $KLIPPYAI_NGINX_SERVER_BLOCK_PATH. Restoring the previous file."
        run_root cp "${KLIPPYAI_NGINX_SERVER_BLOCK_PATH}.bak.${TIMESTAMP}" "$KLIPPYAI_NGINX_SERVER_BLOCK_PATH"
      fi
      die "nginx validation failed after patching $KLIPPYAI_NGINX_SERVER_BLOCK_PATH."
    fi
  fi

  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]]; then
    log "Installing Mainsail custom navigation entry."
    install_mainsail_custom_nav
  fi

  log "Reloading systemd and enabling the service."
  run_root systemctl daemon-reload
  run_root systemctl enable --now "$SERVICE_NAME"

  if [[ "$INSTALL_UPDATE_MACRO" == "yes" ]]; then
    log "Installing UPDATE_KLIPPYAI macro integration."
    install_update_macro_integration
  fi

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    log "Applying OctoEverywhere /klippyai integration patch."
    install_octoeverywhere_integration
  fi

  cat <<EOF

Installation complete
---------------------
Service name:
  $SERVICE_NAME

Environment file:
  /etc/klippyai/klippyai.env

Editable config file:
  $KLIPPYAI_CFG_PATH

Generated nginx snippet:
  /etc/klippyai/nginx-location.conf

KlippyAI runtime log:
  $KLIPPYAI_LOGS_DIR_PATH/$KLIPPYAI_AGENT_LOG_FILE_NAME

Next steps:
1. Restart Moonraker so it reloads the KlippyAI include and allowed-services file:
   sudo systemctl restart moonraker
2. Check the services:
   systemctl status $SERVICE_NAME --no-pager
   systemctl status moonraker --no-pager
   tail -n 100 $KLIPPYAI_LOGS_DIR_PATH/$KLIPPYAI_AGENT_LOG_FILE_NAME
3. Open KlippyAI:
   http://<printer-host>${KLIPPYAI_ROOT_PATH}/
4. After editing ${KLIPPYAI_CFG_PATH}, restart the service:
   sudo systemctl restart $SERVICE_NAME

EOF

  if [[ "$INSTALL_UPDATE_MACRO" == "yes" ]]; then
    cat <<EOF

Klipper update macro:
- Generated macro config: $KLIPPYAI_UPDATE_MACRO_CFG_PATH
- Included from: ${KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH:-<unknown>}
- Helper script: $KLIPPYAI_UPDATE_RUNNER_PATH
- Sudoers entry: $KLIPPYAI_UPDATE_SUDOERS_PATH
- Macro name: UPDATE_KLIPPYAI
- Restart Klipper after install so it loads the new macro:
  sudo systemctl restart $KLIPPYAI_KLIPPER_SERVICE_NAME

EOF
  fi

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    cat <<EOF

OctoEverywhere integration:
- Checkout: $KLIPPYAI_OE_ROOT
- Service: ${KLIPPYAI_OE_SERVICE_NAME:-<restart manually>}
- Navigation target: new tab
- Route: ${KLIPPYAI_ROOT_PATH%/}/

EOF
  fi

  if [[ "$PATCH_NGINX_INCLUDE" == "yes" ]]; then
    cat <<EOF

nginx:
- Patched: $KLIPPYAI_NGINX_SERVER_BLOCK_PATH
- Included snippet: /etc/klippyai/nginx-location.conf
- Reloaded: yes

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KLIPPYAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KLIPPYAI_CFG_PATH}
- the Moonraker integration include is stored in ${KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KLIPPYAI_MAINSAIL_CONFIG_DIR --href ${KLIPPYAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KlippyAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  else
    cat <<EOF

Manual nginx follow-up:
- Add this line inside the Mainsail nginx server block:
  include /etc/klippyai/nginx-location.conf;
- Common file locations are often:
  - /etc/nginx/conf.d/mainsail.conf
  - /etc/nginx/sites-enabled/mainsail
  - /etc/nginx/sites-available/mainsail
- Test and reload nginx:
  sudo nginx -t && sudo systemctl reload nginx

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KLIPPYAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KLIPPYAI_CFG_PATH}
- the Moonraker integration include is stored in ${KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KLIPPYAI_MAINSAIL_CONFIG_DIR --href ${KLIPPYAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KlippyAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  fi
}

main "$@"
