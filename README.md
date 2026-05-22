# KlippyAI

KlippyAI is a Moonraker-integrated assistant for Klipper and Kalico printers. The project is built around a standalone host daemon, a thin Mainsail integration, and a same-origin web UI that can be opened directly from Mainsail without forking or patching Mainsail for `v1`.

The goal is not to create another printer control plane. The goal is to make troubleshooting, configuration work, and guided printer improvements faster and safer by combining deterministic diagnostics with LLM-assisted reasoning.

## What KlippyAI Aims To Fix

Klipper installations are powerful, but the failure modes are often scattered across different places:

- `klippy.log` shows firmware, config, and MCU failures
- `moonraker.log` shows API and service-side problems
- `systemd` or `journalctl` show host-level issues
- the active config tree may contain subtle include and pin mistakes
- UI users often know what they want to achieve, but not the exact Klipper config they need

KlippyAI is meant to close that gap by giving the user one assistant that can:

- inspect logs and explain what failed
- connect symptoms to likely root causes
- suggest the next safest fix to try
- help generate or improve Klipper config fragments
- eventually apply changes through a controlled review-and-approve flow

## Project Direction

The chosen product shape is:

- standalone Linux daemon on the printer host
- Moonraker underneath as the printer-facing boundary
- supported Mainsail custom-navigation link or button in `v1`
- full-page KlippyAI UI served on the same origin at `/klippyai/`

That gives the project:

- operational separation from Moonraker internals
- easy access to printer state and file metadata through Moonraker
- a low-coupling integration that survives normal Mainsail web updates
- a frontend that can evolve without constantly patching Mainsail for every UI change

## Current State

This repository is currently an early scaffold. What exists today:

- FastAPI-based async agent service
- full-page and embedded chat UI served by the agent
- Moonraker client abstraction
- LangGraph diagnostics workflow skeleton
- LangChain provider integration path
- deterministic rule engine for a small set of common Klipper failures
- host-side current `*.log` collection with configurable line-tail excerpts
- runtime file logging to `printer_data/logs/klippyai.log` so host-side debugging is visible from Mainsail
- optional `systemctl` and `journalctl` diagnostics for Moonraker and Klipper services
- one-time printer-profile detection during install, persisted into `klippyai.cfg`
- firmware flavor detection for mainline Klipper, Kalico, and custom forks
- addon and hardware hint detection for common probes, CAN toolhead boards, and companion services
- persisted capability and geometry detection for probe type, accelerometer, filament sensor, build volume, extruder count, bed mesh, and input shaper state
- config assistant workflow with current-config inspection and first-pass managed include proposals across common config categories
- `systemd` and `nginx` deployment examples
- guided installer support for a Mainsail custom-navigation link
- an optional maintained Mainsail source patch bundle for advanced installs

What does not exist yet:

- real Moonraker agent registration flow
- broader host diagnostics beyond the current Moonraker/Klipper service scope
- config diff generation and apply endpoints
- safe write/apply flow
- deeper config specialization beyond the current broad scaffold generation path
- multi-provider support beyond the current initial OpenAI path and local `stub`

## Feature Vision

### Diagnostics

- analyze `klippy.log`, `moonraker.log`, and host/system log excerpts
- auto-collect current `.log` files from `printer_data/logs`
- send only the configured last lines from each collected log file
- collect `systemctl show` snapshots and recent `journalctl` lines for `moonraker.service` and `klipper.service`
- write KlippyAI runtime logs into the same `printer_data/logs` directory used by Klipper-side services
- include the active Klipper config tree as LLM context during diagnostics, not only during config-generation requests
- detect common faults deterministically before involving an LLM
- explain likely causes in plain language
- suggest next actions ordered by safety and usefulness

### Config Assistance

- inspect the current printer config tree including the active root config and its include tree
- auto-detect the active root config and follow its include tree recursively
- generate first-pass managed include proposals in chat
- support broad request classes including fan, macro, sensor, probe, heater, input shaper, bed mesh, filament, CAN toolhead, stepper, extruder, and generic scaffolds
- help users create config snippets for macros, sensors, probes, input shaper, CAN, and similar features
- explain why a given config option is needed
- compare current config with the proposed target state
- generate review-only config proposals instead of modifying printer files

### Printer Awareness

- detect firmware flavor from Moonraker update metadata and Klipper repo origin
- summarize host model, distribution, and static printer identity hints
- infer probe type, accelerometer, filament sensor, camera stack, mainboard MCU hints, toolhead board hints, and common addons once during install
- persist detected identity into `[printer_identity]` in `klippyai.cfg`
- persist detected capabilities into `[printer_capabilities]`
- load the saved printer profile at runtime instead of re-detecting on every request

### Embedded UI

- open from Mainsail through a supported custom-navigation entry
- serve a stable standalone page at `/klippyai/`
- keep the embedded iframe route available at `/klippyai/embed`
- keep all provider API keys server-side only

### Workflow Engine

- use LangGraph for explicit, checkpointed workflows
- use LangChain where it helps with model calls, structured outputs, and tool wiring
- keep host access deterministic and tightly bounded

## Architecture

- `klippyai-agent`: standalone Python daemon on the printer host
- `Moonraker`: canonical source for printer state, managed files, and future integration points
- `Mainsail integration`: supported custom-nav link in `v1`, optional native patch for advanced installs
- `KlippyAI UI`: chat-style assistant UI served from the same origin
- `LangGraph`: orchestration for diagnostics, config proposals, and future approval flows

More detail lives in [docs/architecture.md](docs/architecture.md) and [docs/mainsail-shell.md](docs/mainsail-shell.md).

## Supported Providers

Current code support:

- `stub`: no external LLM call, useful for local UI and deterministic workflow development
- `openai`: backed by `langchain-openai`

Planned provider support is tracked in [BACKLOG.md](BACKLOG.md).

## Installation

### Recommended Path On A Klipper Host

Clone the repository onto the Linux host that already runs Moonraker and Mainsail or Fluidd, then run:

```bash
chmod +x deployment/python/install-python310.sh
./deployment/python/install-python310.sh  # only needed when the host python3 is older than 3.10
chmod +x install.sh
./install.sh
```

Detailed host guidance for that helper lives in [docs/python310-install.md](docs/python310-install.md).

To remove a host install later:

```bash
chmod +x uninstall.sh
./uninstall.sh
```

The installer can now patch the Mainsail nginx server block automatically. By default it offers to update one of these common file paths:

- `/etc/nginx/conf.d/mainsail.conf`
- `/etc/nginx/sites-enabled/mainsail`
- `/etc/nginx/sites-available/mainsail`

The installer currently guides the user through:

- choosing the Linux service user
- confirming the project checkout path, default `/home/<service-user>/KlippyAI`
- selecting the LLM provider
- entering the provider API key when needed
- selecting the model name
- pointing KlippyAI at Moonraker, default `http://127.0.0.1:7125`
- confirming the printer data root, default `/home/<service-user>/printer_data`
- confirming the Mainsail config directory, default `/home/<service-user>/printer_data/config`
- creating a Python virtual environment
- installing the package
- writing `/etc/klippyai/klippyai.env`
- writing `printer_data/config/klippyai.cfg`
- detecting printer profile data once and persisting it into `[printer_identity]` and `[printer_capabilities]`
- writing `klippyai-moonraker.cfg` next to `moonraker.conf` (usually `printer_data/config/klippyai-moonraker.cfg`)
- appending `[include klippyai-moonraker.cfg]` to `moonraker.conf`
- adding `klippyai-agent` to `printer_data/moonraker.asvc`
- generating and enabling a `systemd` service
- generating an nginx location snippet for `/klippyai/`
- optionally patching the selected Mainsail nginx server block to include that snippet
- writing KlippyAI runtime logs to `printer_data/logs/klippyai.log`
- optionally installing a Mainsail navigation link in `.theme/navi.json`
- when `gcode_shell_command` is detected, optionally generating an `UPDATE_KLIPPYAI` macro that pulls the repo and restarts `klippyai-agent`
- when OctoEverywhere is detected, optionally applying the local OE `/klippyai/` route patch automatically

KlippyAI requires Python `3.10+`. The installer now checks that explicitly and recreates an older `.venv` if a previous attempt bootstrapped one with Python `3.9` or older. For Bullseye-era printer images such as BIGTREETECH CB1, use [deployment/python/install-python310.sh](deployment/python/install-python310.sh) or follow [docs/python310-install.md](docs/python310-install.md) before rerunning `./install.sh`.

The installer always asks for the service user first. Path defaults are then derived from that user, so a `biqu` host will naturally default to `/home/biqu/...` instead of `/home/pi/...`.

After installation, the recommended `v1` flow is:

1. reverse-proxy KlippyAI on the same origin at `/klippyai/`
2. let the installer add a supported Mainsail custom-nav entry
3. open KlippyAI from that Mainsail link

Important limitations:

- the optional native Mainsail shell exists as a source patch bundle, but the installer does not apply or build Mainsail automatically
- the optional `UPDATE_KLIPPYAI` macro depends on `gcode_shell_command` support and writes a narrow sudoers rule for its helper script
- changing `service_user` or `project_checkout_path` in `klippyai.cfg` does not rewrite the systemd unit automatically
- Moonraker update-manager controls work best after the repo has semantic-version tags such as `v0.1.0`

### Recommended Mainsail Integration

The supported low-coupling integration is a custom navigation entry in Mainsail's `.theme/navi.json` that points to `/klippyai/` and opens KlippyAI in a new browser tab by default.

The repository includes:

- `integrations/mainsail/install-custom-nav.sh`
- `integrations/mainsail/navi.json.example`

Example navigation entry:

```json
[
  {
    "title": "KlippyAI",
    "href": "/klippyai/",
    "target": "_blank",
    "position": 85
  }
]
```

This is the recommended `v1` path because it uses Mainsail's documented custom-navigation support instead of patching or forking Mainsail just to surface the assistant UI.

### Optional Mainsail Source Patch

An experimental native-shell Mainsail integration still lives in [integrations/mainsail/README.md](integrations/mainsail/README.md), but it is not the default `v1` approach.

It currently targets:

- upstream repository `mainsail-crew/mainsail`
- branch `develop`
- commit `6130a0aa1776a138feaab691b9e4b1334b676b79`
- upstream version `2.17.0`

If you are building a custom Mainsail checkout, apply the patch with:

```bash
chmod +x ./integrations/mainsail/apply-patch.sh
./integrations/mainsail/apply-patch.sh /path/to/mainsail
```

### Optional OctoEverywhere Host Patch

If you want the main OctoEverywhere printer portal to open KlippyAI at
`/klippyai/` without using a Shared Connection URL, the repository now includes
an unsupported host-side patch bundle in
[integrations/octoeverywhere/README.md](integrations/octoeverywhere/README.md).

This patch modifies the local OctoEverywhere checkout, not Mainsail itself. It
adds a `/klippyai/... -> 127.0.0.1:8811/...` route inside OctoEverywhere's
Moonraker-side router and overrides the `KlippyAI` sidebar click behavior when
loaded via `*.octoeverywhere.com`, with support for opening KlippyAI in a new
tab. If the installer detects an OctoEverywhere checkout, it can offer to apply
this patch automatically.

Use it only if you are comfortable carrying a local OctoEverywhere patch across
future OE updates.

### Manual Development Install

#### Windows PowerShell

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
python -m klippyai_agent
```

#### Linux

```bash
python3.10 -m venv .venv  # or any newer python3.x
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
python -m klippyai_agent
```

Then open the standalone UI in a browser:

- local dev: `http://127.0.0.1:8811/`
- reverse-proxied install: `/klippyai/`

## Runtime Configuration

KlippyAI now uses two configuration surfaces:

- `printer_data/config/klippyai.cfg` for host-editable runtime settings
- `/etc/klippyai/klippyai.env` for secrets and bootstrap values such as the config-file path and API key

The installer also creates Moonraker integration files:

- `klippyai-moonraker.cfg` next to `moonraker.conf`, usually `printer_data/config/klippyai-moonraker.cfg`, for the `update_manager` entry
- `printer_data/moonraker.asvc` to allow Moonraker to restart `klippyai-agent` from frontends such as Mainsail
- an `[include klippyai-moonraker.cfg]` line in `moonraker.conf`

`klippyai.cfg` is loaded at service start. After editing it from Mainsail, restart the agent with:

```bash
sudo systemctl restart klippyai-agent
```

The main `klippyai.cfg` values are:

- `service_user`: install metadata for the service account
- `project_checkout_path`: install metadata for the checkout path
- `firmware_flavor`: installer-detected firmware flavor
- `firmware_version`: installer-detected firmware version
- `host_model`: installer-detected host model hint
- `host_distribution`: installer-detected host distribution
- `mainboard`: optional user-declared mainboard model override
- `mainboard_mcu`: installer-detected mainboard MCU hint
- `toolhead`: optional user-declared toolhead model override
- `toolhead_board`: installer-detected toolhead board hint
- `probe_type`: installer-detected probe family, including explicit `none` when no probe is found
- `accelerometer`: installer-detected accelerometer family, including explicit `none`
- `filament_sensor`: installer-detected filament sensor family, including explicit `none`
- `camera_stack`: installer-detected camera stack, currently `crowsnest` or `none`
- `bed_mesh_configured`: whether bed mesh is already configured
- `input_shaper_configured`: whether input shaper is already configured
- `canbus_enabled`: installer-detected CAN presence flag
- `addons`: installer-detected addon list
- `root_config_file`: under `[config_context]`, the detected active root config file, overrideable when your root file is not the standard `printer.cfg`
- `ignore_globs`: under `[config_context]`, optional ignore patterns for KlippyAI context collection, such as backups or archived config directories
- `printer_data_root`: printer data directory, usually `/home/<service-user>/printer_data`
- `mainsail_config_dir`: Mainsail-editable config directory, usually `/home/<service-user>/printer_data/config`
- `moonraker_url`: Moonraker base URL, usually `http://127.0.0.1:7125`
- `root_path`: public reverse-proxy path, usually `/klippyai`
- `port`: local KlippyAI bind port, default `8811`
- `data_dir`: local KlippyAI data directory
- `llm_provider`: currently `stub` or `openai`
- `openai_model`: default OpenAI model name, editable in `klippyai.cfg`
- `agent_log_file_name`, `agent_log_level`, `agent_log_max_bytes`, `agent_log_backup_count`: control the KlippyAI runtime log file under `printer_data/logs`
- `log_tail_lines_default`: default number of lines to include from each current host log file
- `[log_tail_lines]`: per-log overrides keyed by log stem, for example `klippy = 100` and `moonraker = 200`
- `enable_write_actions`: reserved for future work and forced to `false` by the runtime

Environment-file values are intentionally minimal:

- `KLIPPYAI_CONFIG_FILE`: points the service at `klippyai.cfg`
- `KLIPPYAI_OPENAI_API_KEY`: server-side API key for OpenAI

See [deployment/config/klippyai.cfg.example](deployment/config/klippyai.cfg.example) and [.env.example](.env.example) for the current examples.
For Moonraker integration, see [deployment/moonraker/klippyai-moonraker.cfg.example](deployment/moonraker/klippyai-moonraker.cfg.example).

The installer auto-populates `[printer_identity]` and `[printer_capabilities]` once. If KlippyAI misidentifies the printer hardware, capabilities, or firmware flavor, edit those sections in `klippyai.cfg` and restart the service.

If you are upgrading from an older install that still has a `[printer_geometry]` section in `klippyai.cfg`, remove that section before restarting `klippyai-agent`.

Config collection defaults to the active root config file and its include tree. If your config root is nonstandard or you want KlippyAI to skip backup/archive folders, set those under `[config_context]`.

If you want to repopulate the saved printer profile sections from the current host state later, run:

```bash
source /home/<service-user>/KlippyAI/.venv/bin/activate
klippyai-detect-profile \
  --config-file /home/<service-user>/printer_data/config/klippyai.cfg \
  --moonraker-url http://127.0.0.1:7125 \
  --printer-data-root /home/<service-user>/printer_data \
  --overwrite
```

## Security Model

The intended security stance is:

- provider API keys stay server-side only
- the browser never gets raw provider credentials
- host access should come from deterministic tools, not arbitrary shell execution by the LLM
- the current runtime is intentionally shackled and does not write printer/config files
- any future config mutations should go through reviewable diffs and explicit approval
- `v1` should remain diagnostics-first and read-heavy

## Repository Layout

- `src/klippyai_agent/`: application code
- `tests/`: unit tests for deterministic logic
- `docs/architecture.md`: system design and responsibilities
- `docs/mainsail-shell.md`: Mainsail integration plan
- `deployment/systemd/`: service examples
- `deployment/nginx/`: reverse-proxy snippet example
- `deployment/moonraker/`: Moonraker integration example
- `integrations/mainsail/`: supported custom-nav helper plus optional patch bundle
- `install.sh`: guided Linux host installer
- `uninstall.sh`: guided Linux host uninstaller
- `BACKLOG.md`: planned work and milestone backlog

## Development Notes

- The FastAPI app exposes `/`, `/healthz`, `/api/ui-sessions`, `/api/bootstrap`, `/api/chat`, and `/embed`.
- The default provider is `stub`, so the app can boot without any external API key.
- LangGraph checkpointing is wired toward SQLite for local host installs.
- Host log collection currently targets current `.log` files directly under `printer_data/logs` and sends the configured last lines from each file.
- KlippyAI itself also writes a rotating runtime log at `printer_data/logs/klippyai.log`, intended to be visible from Mainsail alongside the other printer-host logs.
- Systemd diagnostics currently target `systemctl show` plus the last `journalctl` lines for the configured Moonraker and Klipper units.
- Config assistant currently inspects `printer_data/config`, follows the active root config include tree, and can return typed config proposals in chat across the main supported feature categories.
- The runtime does not apply or write those proposals back to printer files.
- Printer-profile detection currently runs once during install and uses Moonraker `printer`, `machine`, and `update_manager` APIs together with config parsing and Klipper repo-origin hints.
- Diagnostics prompts now include the current Klipper config snapshot in addition to logs, system context, and the saved printer profile.
- Runtime profile awareness now comes from the saved `[printer_identity]` and `[printer_capabilities]` sections in `klippyai.cfg`.
- Host-editable runtime config now lives in `printer_data/config/klippyai.cfg`, which is intended to be editable from Mainsail.
- The current UI can be opened directly at `/klippyai/` or embedded via `/klippyai/embed`.

## Status And Roadmap

This is still an early-stage project scaffold, not a finished addon. The current best use of the codebase is to establish the architecture and installation flow before adding deeper printer-aware features.

For planned milestones and open work, see [BACKLOG.md](BACKLOG.md).
