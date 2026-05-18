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
- host-side `klippy.log*` and `moonraker.log*` collection with tail-based excerpts
- optional `systemctl` and `journalctl` diagnostics for Moonraker and Klipper services
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
- auto-collect recent `klippy.log*` and `moonraker.log*` files from `printer_data/logs`
- handle both long-lived active logs and rotated archives, including Kalico-style restart rotation
- collect `systemctl show` snapshots and recent `journalctl` lines for `moonraker.service` and `klipper.service`
- detect common faults deterministically before involving an LLM
- explain likely causes in plain language
- suggest next actions ordered by safety and usefulness

### Config Assistance

- inspect the current printer config tree including `printer.cfg` includes
- generate first-pass managed include proposals in chat
- support broad request classes including fan, macro, sensor, probe, heater, input shaper, bed mesh, filament, CAN toolhead, stepper, extruder, and generic scaffolds
- help users create config snippets for macros, sensors, probes, input shaper, CAN, and similar features
- explain why a given config option is needed
- compare current config with the proposed target state
- generate reviewable diffs instead of freeform destructive writes

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
chmod +x install.sh
./install.sh
```

The installer currently guides the user through:

- choosing the Linux service user
- confirming the project checkout path
- selecting the LLM provider
- entering the provider API key when needed
- selecting the model name
- pointing KlippyAI at Moonraker
- confirming the printer data root
- creating a Python virtual environment
- installing the package
- writing `/etc/klippyai/klippyai.env`
- generating and enabling a `systemd` service
- generating an nginx location snippet for `/klippyai/`
- optionally installing a Mainsail navigation link in `.theme/navi.json`

After installation, the recommended `v1` flow is:

1. reverse-proxy KlippyAI on the same origin at `/klippyai/`
2. let the installer add a supported Mainsail custom-nav entry
3. open KlippyAI from that Mainsail link

Important limitations:

- the installer can create the nginx location snippet, but it does not yet patch your Mainsail server block automatically
- the optional native Mainsail shell exists as a source patch bundle, but the installer does not apply or build Mainsail automatically

### Recommended Mainsail Integration

The supported low-coupling integration is a custom navigation entry in Mainsail's `.theme/navi.json` that points to `/klippyai/`.

The repository includes:

- `integrations/mainsail/install-custom-nav.sh`
- `integrations/mainsail/navi.json.example`

Example navigation entry:

```json
[
  {
    "title": "KlippyAI",
    "href": "/klippyai/",
    "target": "_self",
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

### Manual Development Install

#### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
python -m klippyai_agent
```

#### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
python -m klippyai_agent
```

Then open the standalone UI in a browser:

- local dev: `http://127.0.0.1:8811/`
- reverse-proxied install: `/klippyai/`

## Runtime Configuration

The main environment values are:

- `KLIPPYAI_MOONRAKER_URL`: Moonraker base URL, usually `http://127.0.0.1:7125`
- `KLIPPYAI_ROOT_PATH`: public reverse-proxy path, currently intended to be `/klippyai`
- `KLIPPYAI_PORT`: local KlippyAI bind port, default `8811`
- `KLIPPYAI_PRINTER_DATA_ROOT`: printer data directory, usually `/home/pi/printer_data`
- `KLIPPYAI_LLM_PROVIDER`: currently `stub` or `openai`
- `KLIPPYAI_MOONRAKER_SERVICE_NAME`: systemd unit to inspect for Moonraker, default `moonraker.service`
- `KLIPPYAI_KLIPPER_SERVICE_NAME`: systemd unit to inspect for Klipper, default `klipper.service`
- `KLIPPYAI_OPENAI_MODEL`: default OpenAI model name
- `KLIPPYAI_OPENAI_API_KEY`: server-side API key for OpenAI
- `KLIPPYAI_ENABLE_WRITE_ACTIONS`: currently should remain `false`

See [.env.example](.env.example) for the current full set.

## Security Model

The intended security stance is:

- provider API keys stay server-side only
- the browser never gets raw provider credentials
- host access should come from deterministic tools, not arbitrary shell execution by the LLM
- config mutations should always go through reviewable diffs and explicit approval
- `v1` should remain diagnostics-first and read-heavy

## Repository Layout

- `src/klippyai_agent/`: application code
- `tests/`: unit tests for deterministic logic
- `docs/architecture.md`: system design and responsibilities
- `docs/mainsail-shell.md`: Mainsail integration plan
- `deployment/systemd/`: service examples
- `deployment/nginx/`: reverse-proxy snippet example
- `integrations/mainsail/`: supported custom-nav helper plus optional patch bundle
- `install.sh`: guided Linux host installer
- `BACKLOG.md`: planned work and milestone backlog

## Development Notes

- The FastAPI app exposes `/`, `/healthz`, `/api/ui-sessions`, `/api/bootstrap`, `/api/chat`, and `/embed`.
- The default provider is `stub`, so the app can boot without any external API key.
- LangGraph checkpointing is wired toward SQLite for local host installs.
- Host log collection currently targets direct files under `printer_data/logs` and supports both active and rotated `klippy.log*` / `moonraker.log*`, including Kalico-style restart splits.
- Systemd diagnostics currently target `systemctl show` plus the last `journalctl` lines for the configured Moonraker and Klipper units.
- Config assistant currently inspects `printer_data/config`, resolves `printer.cfg` includes, and can return typed config proposals in chat across the main supported feature categories.
- The current UI can be opened directly at `/klippyai/` or embedded via `/klippyai/embed`.

## Status And Roadmap

This is still an early-stage project scaffold, not a finished addon. The current best use of the codebase is to establish the architecture and installation flow before adding deeper printer-aware features.

For planned milestones and open work, see [BACKLOG.md](BACKLOG.md).
