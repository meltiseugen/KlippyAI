#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="KlippyAI"
SERVICE_NAME="klippyai-agent"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
ENV_FILE="/etc/klippyai/klippyai.env"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_SNIPPET_PATH="/etc/klippyai/nginx-location.conf"

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
  local default="${2:-N}"
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

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "This uninstaller only supports Linux hosts."
}

require_cmd() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "Required command not found: $command_name"
}

home_for_user() {
  getent passwd "$1" | cut -d: -f6
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die "sudo is required for uninstall."
    sudo "$@"
  fi
}

run_as_user() {
  local target_user="$1"
  shift

  if [[ "$(id -un)" == "$target_user" ]]; then
    "$@"
    return
  fi

  if [[ "${EUID}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$target_user" -- "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$target_user" -H "$@"
    return
  fi

  die "Unable to switch to user '$target_user'."
}

backup_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root cp "$path" "${path}.bak.${TIMESTAMP}"
    log "Backed up $path to ${path}.bak.${TIMESTAMP}"
  fi
}

extract_env_value() {
  local path="$1"
  local key="$2"
  [[ -f "$path" ]] || return 1

  local line=""
  line="$(grep -E "^${key}=" "$path" | tail -n1 || true)"
  [[ -n "$line" ]] || return 1

  line="${line#*=}"
  if [[ "${line:0:1}" == '"' && "${line: -1}" == '"' ]]; then
    line="${line:1:${#line}-2}"
  fi
  line="${line//\\\"/\"}"
  line="${line//\\\\/\\}"
  printf '%s' "$line"
}

get_cfg_value() {
  local path="$1"
  local section="$2"
  local key="$3"
  [[ -f "$path" ]] || return 1

  awk -v target_section="$section" -v target_key="$key" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    /^\[[^]]+\]/ {
      current = $0
      sub(/^\[/, "", current)
      sub(/\]$/, "", current)
      current = trim(current)
      next
    }
    /^[ \t]*[A-Za-z0-9_.-]+[ \t]*[:=]/ {
      if (current != target_section) {
        next
      }
      line = $0
      sub(/^[ \t]*/, "", line)
      key = line
      sub(/[ \t]*[:=].*$/, "", key)
      key = trim(key)
      if (key != target_key) {
        next
      }
      match(line, /[:=]/)
      value = substr(line, RSTART + 1)
      print trim(value)
      exit
    }
  ' "$path"
}

remove_file_if_present() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root rm -f -- "$path"
    log "Removed $path"
  fi
}

remove_dir_if_present() {
  local path="$1"
  if [[ -d "$path" ]]; then
    run_root rm -rf -- "$path"
    log "Removed $path"
  fi
}

remove_line_from_file() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! grep -Fqx "$line_to_remove" "$path"; then
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
  grep -Fvx "$line_to_remove" "$path" >"$temp_file" || true
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

remove_trimmed_line_from_file() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! awk -v needle="$line_to_remove" '
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
  ' "$path"; then
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

detect_moonraker_config_path() {
  local home_dir="$1"
  local config_dir="$2"
  local candidate=""

  for candidate in \
    "$config_dir/moonraker.conf" \
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

detect_nginx_server_block_path() {
  local candidate=""

  for candidate in \
    /etc/nginx/conf.d/mainsail.conf \
    /etc/nginx/sites-enabled/mainsail \
    /etc/nginx/sites-available/mainsail
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  printf '%s' "/etc/nginx/conf.d/mainsail.conf"
}

reload_nginx() {
  run_root nginx -t
  run_root systemctl reload nginx
}

print_summary() {
  cat <<EOF

Uninstall summary
-----------------
Service unit:          $SYSTEMD_UNIT_PATH
Env file:              $ENV_FILE
KlippyAI cfg:          ${KLIPPYAI_CFG_PATH:-<not found>}
Moonraker config:      ${KLIPPYAI_MOONRAKER_CONFIG_PATH:-<not found>}
Moonraker include:     ${KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH:-<not found>}
Allowed services file: ${KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH:-<not found>}
Mainsail config dir:   ${KLIPPYAI_MAINSAIL_CONFIG_DIR:-<not found>}
Managed config dir:    ${KLIPPYAI_MANAGED_CONFIG_DIR_PATH:-<not found>}
Data dir:              ${KLIPPYAI_DATA_DIR:-<not found>}
Project checkout:      ${KLIPPYAI_PROJECT_CHECKOUT_PATH:-<not found>}
nginx server block:    ${KLIPPYAI_NGINX_SERVER_BLOCK_PATH:-<not found>}
Remove nav entry:      $REMOVE_MAINSAIL_NAV
Remove nginx include:  $REMOVE_NGINX_INCLUDE
Remove data dir:       $REMOVE_DATA_DIR
Remove nginx snippet:  $REMOVE_NGINX_SNIPPET
Remove checkout dir:   $REMOVE_CHECKOUT_DIR
Remove update macro:   $REMOVE_UPDATE_MACRO_INTEGRATION

EOF
}

main() {
  require_linux
  require_cmd awk
  require_cmd getent
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  require_cmd systemctl

  log "Preparing uninstall."

  KLIPPYAI_CFG_PATH="$(extract_env_value "$ENV_FILE" "KLIPPYAI_CONFIG_FILE" || true)"
  if [[ -z "${KLIPPYAI_CFG_PATH:-}" ]]; then
    KLIPPYAI_CFG_PATH="$(prompt_default "Path to klippyai.cfg" "/home/pi/printer_data/config/klippyai/klippyai.cfg")"
  fi

  KLIPPYAI_MAINSAIL_CONFIG_DIR="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "install" "mainsail_config_dir" || true)"
  KLIPPYAI_PRINTER_DATA_ROOT="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "install" "printer_data_root" || true)"
  KLIPPYAI_PROJECT_CHECKOUT_PATH="$(extract_env_value "$ENV_FILE" "KLIPPYAI_PROJECT_CHECKOUT_PATH" || true)"
  if [[ -z "${KLIPPYAI_PROJECT_CHECKOUT_PATH:-}" ]]; then
    KLIPPYAI_PROJECT_CHECKOUT_PATH="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "install" "project_checkout_path" || true)"
  fi
  KLIPPYAI_SERVICE_USER="$(extract_env_value "$ENV_FILE" "KLIPPYAI_SERVICE_USER" || true)"
  if [[ -z "${KLIPPYAI_SERVICE_USER:-}" ]]; then
    KLIPPYAI_SERVICE_USER="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "install" "service_user" || true)"
  fi
  KLIPPYAI_NGINX_SERVER_BLOCK_PATH="$(extract_env_value "$ENV_FILE" "KLIPPYAI_NGINX_SERVER_BLOCK_PATH" || true)"
  if [[ -z "${KLIPPYAI_NGINX_SERVER_BLOCK_PATH:-}" ]]; then
    KLIPPYAI_NGINX_SERVER_BLOCK_PATH="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "install" "nginx_server_block_path" || true)"
  fi
  KLIPPYAI_DATA_DIR="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "server" "data_dir" || true)"

  if [[ -z "${KLIPPYAI_SERVICE_USER:-}" ]] && [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    KLIPPYAI_SERVICE_USER="$SUDO_USER"
  fi
  if [[ -z "${KLIPPYAI_SERVICE_USER:-}" ]]; then
    KLIPPYAI_SERVICE_USER="$(id -un)"
  fi
  KLIPPYAI_SERVICE_HOME="$(home_for_user "$KLIPPYAI_SERVICE_USER" || true)"
  if [[ -z "${KLIPPYAI_SERVICE_HOME:-}" ]]; then
    KLIPPYAI_SERVICE_HOME="/home/${KLIPPYAI_SERVICE_USER}"
  fi

  if [[ -z "${KLIPPYAI_MAINSAIL_CONFIG_DIR:-}" ]] && [[ -n "${KLIPPYAI_PRINTER_DATA_ROOT:-}" ]]; then
    KLIPPYAI_MAINSAIL_CONFIG_DIR="${KLIPPYAI_PRINTER_DATA_ROOT%/}/config"
  fi
  if [[ -z "${KLIPPYAI_PRINTER_DATA_ROOT:-}" ]]; then
    KLIPPYAI_PRINTER_DATA_ROOT="${KLIPPYAI_SERVICE_HOME%/}/printer_data"
  fi
  if [[ -z "${KLIPPYAI_PROJECT_CHECKOUT_PATH:-}" ]]; then
    KLIPPYAI_PROJECT_CHECKOUT_PATH="${KLIPPYAI_SERVICE_HOME%/}/KlippyAI"
  fi
  if [[ -z "${KLIPPYAI_DATA_DIR:-}" ]]; then
    KLIPPYAI_DATA_DIR="/var/lib/klippyai"
  fi
  if [[ -z "${KLIPPYAI_MAINSAIL_CONFIG_DIR:-}" ]]; then
    KLIPPYAI_MAINSAIL_CONFIG_DIR="${KLIPPYAI_SERVICE_HOME%/}/printer_data/config"
  fi
  KLIPPYAI_MANAGED_CONFIG_DIR_NAME="$(extract_env_value "$ENV_FILE" "KLIPPYAI_MANAGED_CONFIG_DIR_NAME" || true)"
  if [[ -z "${KLIPPYAI_MANAGED_CONFIG_DIR_NAME:-}" ]]; then
    KLIPPYAI_MANAGED_CONFIG_DIR_NAME="klippyai"
  fi
  KLIPPYAI_MANAGED_CONFIG_DIR_PATH="${KLIPPYAI_CFG_PATH%/*}"
  if [[ "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH" == "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]]; then
    KLIPPYAI_MANAGED_CONFIG_DIR_PATH="${KLIPPYAI_MAINSAIL_CONFIG_DIR%/}/$KLIPPYAI_MANAGED_CONFIG_DIR_NAME"
  fi
  if [[ -z "${KLIPPYAI_NGINX_SERVER_BLOCK_PATH:-}" ]]; then
    KLIPPYAI_NGINX_SERVER_BLOCK_PATH="$(detect_nginx_server_block_path)"
  fi

  KLIPPYAI_MOONRAKER_CONFIG_PATH="$(detect_moonraker_config_path "$KLIPPYAI_SERVICE_HOME" "$KLIPPYAI_MAINSAIL_CONFIG_DIR")"
  KLIPPYAI_MOONRAKER_CONFIG_DIR="${KLIPPYAI_MOONRAKER_CONFIG_PATH%/*}"
  KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH="${KLIPPYAI_MANAGED_CONFIG_DIR_PATH}/klippyai-moonraker.cfg"
  KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH="${KLIPPYAI_PRINTER_DATA_ROOT%/}/moonraker.asvc"
  KLIPPYAI_MAINSAIL_NAV_HREF="/klippyai/"
  KLIPPYAI_UPDATE_RUNNER_PATH="/usr/local/bin/klippyai-self-update"
  KLIPPYAI_UPDATE_SUDOERS_PATH="/etc/sudoers.d/klippyai-self-update"
  KLIPPYAI_UPDATE_MACRO_CFG_PATH="${KLIPPYAI_MANAGED_CONFIG_DIR_PATH}/klippyai-macros.cfg"
  if [[ ! -f "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH" && -f "${KLIPPYAI_MOONRAKER_CONFIG_DIR}/klippyai-moonraker.cfg" ]]; then
    KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH="${KLIPPYAI_MOONRAKER_CONFIG_DIR}/klippyai-moonraker.cfg"
  fi
  if [[ ! -f "$KLIPPYAI_UPDATE_MACRO_CFG_PATH" && -f "${KLIPPYAI_MAINSAIL_CONFIG_DIR%/}/klippyai-update-macro.cfg" ]]; then
    KLIPPYAI_UPDATE_MACRO_CFG_PATH="${KLIPPYAI_MAINSAIL_CONFIG_DIR%/}/klippyai-update-macro.cfg"
  fi
  KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE="$(get_cfg_value "$KLIPPYAI_CFG_PATH" "config_context" "root_config_file" || true)"
  KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE="$(trim_whitespace "$KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE")"
  if [[ -z "${KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE:-}" ]]; then
    KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH="${KLIPPYAI_MAINSAIL_CONFIG_DIR%/}/printer.cfg"
  elif [[ "$KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE" == /* ]]; then
    KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH="$KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE"
  else
    KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH="${KLIPPYAI_MAINSAIL_CONFIG_DIR%/}/$KLIPPYAI_KLIPPER_ROOT_CONFIG_VALUE"
  fi

  if confirm "Remove the Mainsail custom-navigation entry?" "Y"; then
    REMOVE_MAINSAIL_NAV="yes"
  else
    REMOVE_MAINSAIL_NAV="no"
  fi

  if [[ -f "${KLIPPYAI_NGINX_SERVER_BLOCK_PATH:-}" ]] && confirm "Remove the KlippyAI nginx include line from ${KLIPPYAI_NGINX_SERVER_BLOCK_PATH}?" "Y"; then
    REMOVE_NGINX_INCLUDE="yes"
  else
    REMOVE_NGINX_INCLUDE="no"
  fi

  if confirm "Remove the KlippyAI data directory (${KLIPPYAI_DATA_DIR})?" "N"; then
    REMOVE_DATA_DIR="yes"
  else
    REMOVE_DATA_DIR="no"
  fi

  if confirm "Delete the nginx snippet file (${NGINX_SNIPPET_PATH}) now?" "N"; then
    REMOVE_NGINX_SNIPPET="yes"
  else
    REMOVE_NGINX_SNIPPET="no"
  fi

  if [[ "$REMOVE_NGINX_SNIPPET" == "yes" && "$REMOVE_NGINX_INCLUDE" != "yes" ]]; then
    die "Refusing to delete ${NGINX_SNIPPET_PATH} while keeping its nginx include line. Remove the include line first or keep the snippet file."
  fi

  if confirm "Delete the project checkout directory (${KLIPPYAI_PROJECT_CHECKOUT_PATH})?" "N"; then
    REMOVE_CHECKOUT_DIR="yes"
  else
    REMOVE_CHECKOUT_DIR="no"
  fi

  if [[ -f "$KLIPPYAI_UPDATE_MACRO_CFG_PATH" || -f "$KLIPPYAI_UPDATE_RUNNER_PATH" || -f "$KLIPPYAI_UPDATE_SUDOERS_PATH" ]]; then
    if confirm "Remove the optional UPDATE_KLIPPYAI macro integration?" "Y"; then
      REMOVE_UPDATE_MACRO_INTEGRATION="yes"
    else
      REMOVE_UPDATE_MACRO_INTEGRATION="no"
    fi
  else
    REMOVE_UPDATE_MACRO_INTEGRATION="no"
  fi

  print_summary
  confirm "Proceed with uninstall?" "N" || die "Uninstall cancelled."

  if systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
    log "Stopping and disabling ${SERVICE_NAME}."
    run_root systemctl disable --now "$SERVICE_NAME" || warn "Could not fully disable ${SERVICE_NAME}."
  fi

  remove_file_if_present "$SYSTEMD_UNIT_PATH"
  run_root systemctl daemon-reload

  if [[ "$REMOVE_MAINSAIL_NAV" == "yes" ]] && [[ -d "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]]; then
    if command -v python3 >/dev/null 2>&1 && [[ -f "$KLIPPYAI_PROJECT_CHECKOUT_PATH/integrations/mainsail/uninstall-custom-nav.sh" ]]; then
      if id "$KLIPPYAI_SERVICE_USER" >/dev/null 2>&1; then
        run_as_user "$KLIPPYAI_SERVICE_USER" bash "$KLIPPYAI_PROJECT_CHECKOUT_PATH/integrations/mainsail/uninstall-custom-nav.sh" \
          --config-dir "$KLIPPYAI_MAINSAIL_CONFIG_DIR" \
          --href "$KLIPPYAI_MAINSAIL_NAV_HREF" \
          --title "KlippyAI"
      else
        warn "Skipping Mainsail nav removal because the service user '$KLIPPYAI_SERVICE_USER' does not exist."
      fi
    else
      warn "Skipping Mainsail nav removal because python3 or uninstall-custom-nav.sh is unavailable."
    fi
  fi

  if [[ -f "$KLIPPYAI_MOONRAKER_CONFIG_PATH" ]]; then
    remove_line_from_file "$KLIPPYAI_MOONRAKER_CONFIG_PATH" "$(build_include_line "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH" "$KLIPPYAI_MOONRAKER_CONFIG_PATH")"
  fi
  remove_file_if_present "$KLIPPYAI_MOONRAKER_EXTENSION_CFG_PATH"
  remove_line_from_file "$KLIPPYAI_MOONRAKER_ALLOWED_SERVICES_PATH" "$SERVICE_NAME"
  remove_file_if_present "$KLIPPYAI_CFG_PATH"
  remove_file_if_present "$ENV_FILE"

  if [[ "$REMOVE_UPDATE_MACRO_INTEGRATION" == "yes" ]]; then
    if [[ -f "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH" ]]; then
      remove_line_from_file "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH" "$(build_include_line "$KLIPPYAI_UPDATE_MACRO_CFG_PATH" "$KLIPPYAI_KLIPPER_ROOT_CONFIG_PATH")"
    fi
    remove_file_if_present "$KLIPPYAI_UPDATE_MACRO_CFG_PATH"
    remove_file_if_present "$KLIPPYAI_UPDATE_RUNNER_PATH"
    remove_file_if_present "$KLIPPYAI_UPDATE_SUDOERS_PATH"
  fi

  if [[ -n "${KLIPPYAI_MANAGED_CONFIG_DIR_PATH:-}" ]] && [[ -d "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH" ]]; then
    if [[ -z "$(find "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      remove_dir_if_present "$KLIPPYAI_MANAGED_CONFIG_DIR_PATH"
    fi
  fi

  if [[ "$REMOVE_NGINX_INCLUDE" == "yes" ]]; then
    remove_trimmed_line_from_file "$KLIPPYAI_NGINX_SERVER_BLOCK_PATH" "include ${NGINX_SNIPPET_PATH};"
    log "Testing and reloading nginx."
    reload_nginx
  fi

  if [[ "$REMOVE_NGINX_SNIPPET" == "yes" ]]; then
    remove_file_if_present "$NGINX_SNIPPET_PATH"
  fi

  if [[ "$REMOVE_DATA_DIR" == "yes" ]]; then
    remove_dir_if_present "$KLIPPYAI_DATA_DIR"
  fi

  if [[ "$REMOVE_CHECKOUT_DIR" == "yes" ]]; then
    if [[ -n "$KLIPPYAI_PROJECT_CHECKOUT_PATH" && "$KLIPPYAI_PROJECT_CHECKOUT_PATH" != "/" ]]; then
      cd /
      remove_dir_if_present "$KLIPPYAI_PROJECT_CHECKOUT_PATH"
    else
      warn "Refusing to remove an unsafe checkout path: ${KLIPPYAI_PROJECT_CHECKOUT_PATH:-<empty>}"
    fi
  fi

  cat <<EOF

Uninstall complete
------------------
Removed:
- systemd unit for ${SERVICE_NAME}
- KlippyAI runtime config
- Moonraker include entry and allowed-services entry
- KlippyAI environment file
- optional UPDATE_KLIPPYAI macro artifacts when selected

Manual follow-up:
1. Restart Moonraker:
   sudo systemctl restart moonraker
2. If you kept the nginx include line or the snippet file, test and reload nginx:
   sudo nginx -t && sudo systemctl reload nginx
3. If you kept the checkout directory, you can remove it later manually.

EOF
}

main "$@"
