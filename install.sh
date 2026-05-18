#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="KlippyAI"
SERVICE_NAME="klippyai-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

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

maybe_install_python_packages() {
  if command -v python3 >/dev/null 2>&1; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if confirm "python3 is missing. Install python3, python3-venv, and python3-pip with apt?" "Y"; then
      run_root apt-get update
      run_root apt-get install -y python3 python3-venv python3-pip
      return
    fi
  fi

  die "python3 is required."
}

ensure_python_venv() {
  if python3 -m venv --help >/dev/null 2>&1; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if confirm "python3-venv is missing. Install python3-venv with apt?" "Y"; then
      run_root apt-get update
      run_root apt-get install -y python3-venv
      return
    fi
  fi

  die "python3 venv support is required."
}

detect_default_install_user() {
  if [[ "${EUID}" -eq 0 ]] && [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    printf '%s' "${SUDO_USER}"
    return
  fi
  id -un
}

home_for_user() {
  getent passwd "$1" | cut -d: -f6
}

detect_printer_data_root() {
  local home_dir="$1"
  local candidate=""

  for candidate in \
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

write_env_file() {
  local temp_file
  temp_file="$(mktemp)"

  {
    printf 'KLIPPYAI_HOST="%s"\n' "$(escape_env_value "127.0.0.1")"
    printf 'KLIPPYAI_PORT="%s"\n' "$(escape_env_value "$KLIPPYAI_PORT")"
    printf 'KLIPPYAI_ROOT_PATH="%s"\n' "$(escape_env_value "$KLIPPYAI_ROOT_PATH")"
    printf 'KLIPPYAI_PUBLIC_BASE_URL="%s"\n' "$(escape_env_value "$KLIPPYAI_PUBLIC_BASE_URL")"
    printf 'KLIPPYAI_MOONRAKER_URL="%s"\n' "$(escape_env_value "$KLIPPYAI_MOONRAKER_URL")"
    printf 'KLIPPYAI_DATA_DIR="%s"\n' "$(escape_env_value "$KLIPPYAI_DATA_DIR")"
    printf 'KLIPPYAI_CHECKPOINT_DB="%s"\n' "$(escape_env_value "$KLIPPYAI_CHECKPOINT_DB")"
    printf 'KLIPPYAI_PRINTER_DATA_ROOT="%s"\n' "$(escape_env_value "$KLIPPYAI_PRINTER_DATA_ROOT")"
    printf 'KLIPPYAI_COLLECT_HOST_LOGS="%s"\n' "$(escape_env_value "$KLIPPYAI_COLLECT_HOST_LOGS")"
    printf 'KLIPPYAI_LOGS_DIR_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_LOGS_DIR_NAME")"
    printf 'KLIPPYAI_LOG_MAX_FILES_PER_FAMILY="%s"\n' "$(escape_env_value "$KLIPPYAI_LOG_MAX_FILES_PER_FAMILY")"
    printf 'KLIPPYAI_LOG_ACTIVE_TAIL_BYTES="%s"\n' "$(escape_env_value "$KLIPPYAI_LOG_ACTIVE_TAIL_BYTES")"
    printf 'KLIPPYAI_LOG_ROTATED_TAIL_BYTES="%s"\n' "$(escape_env_value "$KLIPPYAI_LOG_ROTATED_TAIL_BYTES")"
    printf 'KLIPPYAI_LOG_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPYAI_LOG_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPYAI_COLLECT_SYSTEMD_DIAGNOSTICS="%s"\n' "$(escape_env_value "$KLIPPYAI_COLLECT_SYSTEMD_DIAGNOSTICS")"
    printf 'KLIPPYAI_MOONRAKER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_MOONRAKER_SERVICE_NAME")"
    printf 'KLIPPYAI_KLIPPER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPYAI_KLIPPER_SERVICE_NAME")"
    printf 'KLIPPYAI_JOURNAL_LINES="%s"\n' "$(escape_env_value "$KLIPPYAI_JOURNAL_LINES")"
    printf 'KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="%s"\n' "$(escape_env_value "$KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS")"
    printf 'KLIPPYAI_LLM_PROVIDER="%s"\n' "$(escape_env_value "$KLIPPYAI_LLM_PROVIDER")"
    printf 'KLIPPYAI_OPENAI_MODEL="%s"\n' "$(escape_env_value "$KLIPPYAI_OPENAI_MODEL")"
    printf 'KLIPPYAI_OPENAI_API_KEY="%s"\n' "$(escape_env_value "$KLIPPYAI_OPENAI_API_KEY")"
    printf 'KLIPPYAI_ENABLE_WRITE_ACTIONS="%s"\n' "$(escape_env_value "$KLIPPYAI_ENABLE_WRITE_ACTIONS")"
  } >"$temp_file"

  run_root install -d -m 755 /etc/klippyai
  backup_file /etc/klippyai/klippyai.env
  run_root install -m 600 "$temp_file" /etc/klippyai/klippyai.env
  rm -f "$temp_file"
}

write_systemd_service() {
  local temp_file
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
ReadWritePaths=$KLIPPYAI_DATA_DIR $KLIPPYAI_PRINTER_DATA_ROOT

[Install]
WantedBy=multi-user.target
EOF

  backup_file "/etc/systemd/system/${SERVICE_NAME}.service"
  run_root install -m 644 "$temp_file" "/etc/systemd/system/${SERVICE_NAME}.service"
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

install_mainsail_custom_nav() {
  [[ -n "${KLIPPYAI_MAINSAIL_CONFIG_DIR:-}" ]] || die "Mainsail config directory is not set."
  [[ -d "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]] || die "Mainsail config directory does not exist: $KLIPPYAI_MAINSAIL_CONFIG_DIR"

  local href="${KLIPPYAI_ROOT_PATH%/}/"
  run_as_user bash "$INSTALL_DIR/integrations/mainsail/install-custom-nav.sh" \
    --config-dir "$KLIPPYAI_MAINSAIL_CONFIG_DIR" \
    --href "$href" \
    --title "KlippyAI" \
    --target "_self" \
    --position 85
}

print_summary() {
  cat <<EOF

Install summary
---------------
User:                 $INSTALL_USER
Project checkout:     $INSTALL_DIR
Moonraker URL:        $KLIPPYAI_MOONRAKER_URL
Printer data root:    $KLIPPYAI_PRINTER_DATA_ROOT
Mainsail config dir:  $KLIPPYAI_MAINSAIL_CONFIG_DIR
Provider:             $KLIPPYAI_LLM_PROVIDER
Model:                $KLIPPYAI_OPENAI_MODEL
Root path:            $KLIPPYAI_ROOT_PATH
Local bind port:      $KLIPPYAI_PORT
Data dir:             $KLIPPYAI_DATA_DIR
Write actions:        $KLIPPYAI_ENABLE_WRITE_ACTIONS
Mainsail nav link:    $INSTALL_MAINSAIL_NAV

EOF
}

main() {
  require_linux
  require_cmd getent
  require_cmd find
  require_cmd install
  require_cmd systemctl

  [[ -f "$SCRIPT_DIR/pyproject.toml" ]] || die "Run this installer from a KlippyAI checkout."

  log "Preparing interactive installation."

  DEFAULT_INSTALL_USER="$(detect_default_install_user)"
  INSTALL_USER="$(prompt_default "Linux user that should run the KlippyAI service" "$DEFAULT_INSTALL_USER")"
  id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist."

  INSTALL_HOME="$(home_for_user "$INSTALL_USER")"
  [[ -n "$INSTALL_HOME" ]] || die "Could not determine the home directory for '$INSTALL_USER'."

  INSTALL_DIR="$(prompt_default "Project checkout path to install from" "$SCRIPT_DIR")"
  ensure_no_spaces "$INSTALL_DIR" "Project checkout path"
  [[ -f "$INSTALL_DIR/pyproject.toml" ]] || die "No pyproject.toml found in $INSTALL_DIR."
  run_as_user test -r "$INSTALL_DIR/pyproject.toml" || die "User '$INSTALL_USER' cannot read $INSTALL_DIR."
  run_as_user test -w "$INSTALL_DIR" || die "User '$INSTALL_USER' must be able to write to $INSTALL_DIR."

  DEFAULT_PRINTER_DATA_ROOT="$(detect_printer_data_root "$INSTALL_HOME")"
  KLIPPYAI_PRINTER_DATA_ROOT="$(prompt_default "Printer data root" "$DEFAULT_PRINTER_DATA_ROOT")"
  ensure_no_spaces "$KLIPPYAI_PRINTER_DATA_ROOT" "Printer data root"
  KLIPPYAI_MAINSAIL_CONFIG_DIR="$(prompt_default "Mainsail config directory" "$KLIPPYAI_PRINTER_DATA_ROOT/config")"
  ensure_no_spaces "$KLIPPYAI_MAINSAIL_CONFIG_DIR" "Mainsail config directory"

  KLIPPYAI_MOONRAKER_URL="$(prompt_default "Moonraker URL" "http://127.0.0.1:7125")"
  KLIPPYAI_ROOT_PATH="$(normalize_root_path "$(prompt_default "Reverse-proxy root path" "/klippyai")")"
  KLIPPYAI_PORT="$(prompt_default "Local KlippyAI bind port" "8811")"
  ensure_numeric_port "$KLIPPYAI_PORT"
  KLIPPYAI_PUBLIC_BASE_URL="http://127.0.0.1:${KLIPPYAI_PORT}"
  KLIPPYAI_DATA_DIR="$(prompt_default "Local KlippyAI data directory" "/var/lib/klippyai")"
  ensure_no_spaces "$KLIPPYAI_DATA_DIR" "Local data directory"
  KLIPPYAI_CHECKPOINT_DB="${KLIPPYAI_DATA_DIR}/checkpoints.sqlite"
  KLIPPYAI_COLLECT_HOST_LOGS="true"
  KLIPPYAI_LOGS_DIR_NAME="logs"
  KLIPPYAI_LOG_MAX_FILES_PER_FAMILY="3"
  KLIPPYAI_LOG_ACTIVE_TAIL_BYTES="160000"
  KLIPPYAI_LOG_ROTATED_TAIL_BYTES="80000"
  KLIPPYAI_LOG_ARTIFACT_CHAR_LIMIT="18000"
  KLIPPYAI_COLLECT_SYSTEMD_DIAGNOSTICS="true"
  KLIPPYAI_MOONRAKER_SERVICE_NAME="moonraker.service"
  KLIPPYAI_KLIPPER_SERVICE_NAME="klipper.service"
  KLIPPYAI_JOURNAL_LINES="200"
  KLIPPYAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="6000"
  KLIPPYAI_JOURNAL_ARTIFACT_CHAR_LIMIT="16000"
  KLIPPYAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="6"

  KLIPPYAI_LLM_PROVIDER="$(prompt_default "LLM provider (currently: openai or stub)" "openai")"
  KLIPPYAI_LLM_PROVIDER="${KLIPPYAI_LLM_PROVIDER,,}"
  KLIPPYAI_OPENAI_MODEL="$(prompt_default "Model name" "gpt-5-mini")"
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

  if confirm "Enable write actions now?" "N"; then
    KLIPPYAI_ENABLE_WRITE_ACTIONS="true"
    warn "Write actions are not implemented yet. Enabling this now is not recommended for production use."
  else
    KLIPPYAI_ENABLE_WRITE_ACTIONS="false"
  fi

  if confirm "Install a Mainsail custom-navigation link to KlippyAI?" "Y"; then
    INSTALL_MAINSAIL_NAV="yes"
  else
    INSTALL_MAINSAIL_NAV="no"
  fi

  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]] && [[ ! -d "$KLIPPYAI_MAINSAIL_CONFIG_DIR" ]]; then
    die "Mainsail config directory does not exist: $KLIPPYAI_MAINSAIL_CONFIG_DIR"
  fi

  print_summary
  confirm "Proceed with installation?" "Y" || die "Installation cancelled."

  maybe_install_python_packages
  ensure_python_venv

  log "Creating service data directory."
  run_root install -d -m 755 "$KLIPPYAI_DATA_DIR"
  run_root chown "$INSTALL_USER" "$KLIPPYAI_DATA_DIR"

  log "Creating Python virtual environment."
  if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    run_as_user python3 -m venv "$INSTALL_DIR/.venv"
  fi

  log "Installing Python package into the virtual environment."
  run_as_user "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
  run_as_user "$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR"

  log "Writing /etc/klippyai/klippyai.env"
  write_env_file

  log "Writing systemd service."
  write_systemd_service

  log "Generating nginx location snippet."
  write_nginx_snippet

  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]]; then
    log "Installing Mainsail custom navigation entry."
    install_mainsail_custom_nav
  fi

  log "Reloading systemd and enabling the service."
  run_root systemctl daemon-reload
  run_root systemctl enable --now "$SERVICE_NAME"

  cat <<EOF

Installation complete
---------------------
Service name:
  $SERVICE_NAME

Environment file:
  /etc/klippyai/klippyai.env

Generated nginx snippet:
  /etc/klippyai/nginx-location.conf

Next steps:
1. Add this line inside the Mainsail nginx server block:
   include /etc/klippyai/nginx-location.conf;
2. Test and reload nginx:
   sudo nginx -t && sudo systemctl reload nginx
3. Check the service:
   systemctl status $SERVICE_NAME --no-pager
4. Open KlippyAI:
   http://<printer-host>${KLIPPYAI_ROOT_PATH}/

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KLIPPYAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KLIPPYAI_MAINSAIL_CONFIG_DIR --href ${KLIPPYAI_ROOT_PATH%/}/

Current limitations:
- the installer generates the reverse-proxy snippet, but it does not patch nginx automatically
- the optional native Mainsail drawer patch is not installed by this script

EOF
}

main "$@"
