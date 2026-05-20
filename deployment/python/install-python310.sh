#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="KlippyAI Python"
PYTHON_VERSION="${PYTHON_VERSION:-3.10.20}"
PYTHON_SERIES="${PYTHON_VERSION%.*}"
INSTALL_PREFIX="${INSTALL_PREFIX:-/usr/local}"
BUILD_JOBS="${BUILD_JOBS:-}"
ENABLE_OPTIMIZATIONS="${ENABLE_OPTIMIZATIONS:-0}"
WORK_DIR=""

log() {
  printf '[%s] %s\n' "$PROJECT_NAME" "$*"
}

die() {
  printf '[%s] error: %s\n' "$PROJECT_NAME" "$*" >&2
  exit 1
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die "sudo is required."
    sudo "$@"
  fi
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "This installer only supports Linux hosts."
}

ensure_numeric() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$label must be numeric."
}

ensure_build_jobs() {
  local cpu_count=2

  if [[ -n "$BUILD_JOBS" ]]; then
    ensure_numeric "$BUILD_JOBS" "BUILD_JOBS"
    (( BUILD_JOBS >= 1 )) || die "BUILD_JOBS must be at least 1."
    return
  fi

  if command -v nproc >/dev/null 2>&1; then
    cpu_count="$(nproc)"
  fi

  if (( cpu_count < 1 )); then
    cpu_count=1
  elif (( cpu_count > 2 )); then
    cpu_count=2
  fi

  BUILD_JOBS="$cpu_count"
}

python_command_path() {
  local candidate="python${PYTHON_SERIES}"
  if command -v "$candidate" >/dev/null 2>&1; then
    command -v "$candidate"
    return
  fi

  printf '%s/bin/%s' "${INSTALL_PREFIX%/}" "$candidate"
}

python_ready() {
  local python_bin="$1"
  [[ -x "$python_bin" ]] || return 1
  "$python_bin" -m venv --help >/dev/null 2>&1
}

apt_has_package() {
  local package_name="$1"
  apt-cache show "$package_name" >/dev/null 2>&1
}

install_via_apt() {
  local python_pkg="python${PYTHON_SERIES}"
  local venv_pkg="python${PYTHON_SERIES}-venv"

  command -v apt-get >/dev/null 2>&1 || return 1
  command -v apt-cache >/dev/null 2>&1 || return 1
  run_root apt-get update

  if ! apt_has_package "$python_pkg" || ! apt_has_package "$venv_pkg"; then
    return 1
  fi

  log "Installing $python_pkg and $venv_pkg from apt."
  run_root apt-get install -y "$python_pkg" "$venv_pkg"
  return 0
}

install_build_dependencies() {
  command -v apt-get >/dev/null 2>&1 || die "Automatic source build requires apt-get on this host."

  log "Installing Python build dependencies."
  run_root apt-get update
  run_root apt-get install -y \
    build-essential \
    wget \
    ca-certificates \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    libffi-dev \
    libgdbm-dev \
    liblzma-dev \
    tk-dev \
    uuid-dev
}

cleanup() {
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}

download_python_source() {
  local tarball="$WORK_DIR/Python-${PYTHON_VERSION}.tgz"
  local url="https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"

  log "Downloading Python ${PYTHON_VERSION} source."
  wget -O "$tarball" "$url"
  tar -xzf "$tarball" -C "$WORK_DIR"
}

build_from_source() {
  local source_dir=""
  local configure_args=(
    "--prefix=${INSTALL_PREFIX}"
    "--with-ensurepip=upgrade"
  )

  if [[ "$ENABLE_OPTIMIZATIONS" == "1" ]]; then
    configure_args+=("--enable-optimizations")
  elif [[ "$ENABLE_OPTIMIZATIONS" != "0" ]]; then
    die "ENABLE_OPTIMIZATIONS must be 0 or 1."
  fi

  install_build_dependencies
  WORK_DIR="$(mktemp -d /tmp/klippyai-python310.XXXXXX)"
  trap cleanup EXIT

  download_python_source

  source_dir="$WORK_DIR/Python-${PYTHON_VERSION}"
  cd "$source_dir"

  log "Configuring Python ${PYTHON_VERSION}."
  ./configure "${configure_args[@]}"

  log "Building Python ${PYTHON_VERSION} with $BUILD_JOBS job(s)."
  make -j"$BUILD_JOBS"

  log "Installing Python ${PYTHON_VERSION} with altinstall."
  run_root make altinstall
  hash -r
}

verify_install() {
  local python_bin
  python_bin="$(python_command_path)"

  python_ready "$python_bin" || die "Python ${PYTHON_SERIES} was installed but venv support is not working."

  log "Installed $("$python_bin" --version 2>&1)"
  log "Verified: $python_bin -m venv"
}

main() {
  local python_bin=""

  require_linux
  ensure_build_jobs

  python_bin="$(python_command_path)"
  if python_ready "$python_bin"; then
    log "Python ${PYTHON_SERIES} is already installed at $python_bin."
    log "Nothing to do."
    return
  fi

  if ! install_via_apt; then
    build_from_source
  fi

  verify_install
  log "Next step: rerun ./install.sh from the KlippyAI checkout."
}

main "$@"
