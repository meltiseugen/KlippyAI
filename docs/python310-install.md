# Installing Python 3.10 For KlippyAI

KlippyAI requires Python `3.10+`.

This repository includes a helper script for Linux printer hosts that need Python `3.10` installed before `./install.sh` can create the project virtual environment.

## Quick Path

From the KlippyAI checkout:

```bash
chmod +x ./deployment/python/install-python310.sh
./deployment/python/install-python310.sh
python3.10 --version
python3.10 -m venv --help
```

Then rerun the main installer:

```bash
rm -rf .venv
./install.sh
```

If `.venv` does not exist yet, you can skip the `rm -rf .venv` step.

## What The Helper Script Does

`deployment/python/install-python310.sh` uses two paths:

1. If the host package manager already provides `python3.10` and `python3.10-venv`, it installs those packages with `apt`.
2. If those packages are not available, it installs the required build dependencies, downloads CPython `3.10.20` from `python.org`, and installs it with `make altinstall`.

`make altinstall` is important because it installs `python3.10` alongside the system Python instead of replacing `/usr/bin/python3`.

That is the intended path for boards such as BIGTREETECH CB1 images based on Debian 11 / Bullseye, where the distro default `python3` is usually `3.9`.

## Defaults And Options

The helper script is designed for low-memory printer hosts:

- it defaults to at most `2` build jobs
- it does not enable CPython PGO/LTO optimizations by default

Optional environment variables:

- `BUILD_JOBS=1` or `BUILD_JOBS=2`: override the compiler parallelism
- `ENABLE_OPTIMIZATIONS=1`: add `./configure --enable-optimizations`
- `PYTHON_VERSION=3.10.20`: override the exact CPython patch release
- `INSTALL_PREFIX=/usr/local`: override the install prefix used by `make altinstall`

Example with explicit options:

```bash
BUILD_JOBS=2 ENABLE_OPTIMIZATIONS=1 ./deployment/python/install-python310.sh
```

## Manual Install Path

If you prefer to install Python manually instead of using the helper script:

```bash
sudo apt update
sudo apt install -y build-essential wget ca-certificates \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libncursesw5-dev libffi-dev libgdbm-dev liblzma-dev tk-dev uuid-dev

cd /tmp
wget https://www.python.org/ftp/python/3.10.20/Python-3.10.20.tgz
tar -xzf Python-3.10.20.tgz
cd Python-3.10.20
./configure
make -j2
sudo make altinstall
```

Then verify:

```bash
python3.10 --version
python3.10 -m venv --help
```

## Notes

- A source build can take a while on SBC hardware.
- `ENABLE_OPTIMIZATIONS=1` is optional. It produces a more optimized interpreter, but the build takes longer and uses more CPU and memory.
- The KlippyAI installer will recreate an existing `.venv` if it was previously built with Python `3.9` or older.
