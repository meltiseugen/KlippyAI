# Architecture

## Goals

KlippyAI should help users debug, fix, and improve Klipper/Kalico printers without becoming a second printer control plane. The system should remain operationally separate from Moonraker while using Moonraker as the canonical interface for printer data and actions.

## Chosen Topology

- Standalone host daemon
- Moonraker integration underneath
- Mainsail custom-navigation entry in `v1`
- Same-origin KlippyAI UI at `/klippyai/`

## Component Boundaries

### 1. Agent Service

The agent is a separate async Python service that owns:

- LLM provider configuration
- workflow orchestration
- log and config analysis
- future patch generation and safe apply flows
- local persistence
- embedded UI hosting

The agent should not replace Moonraker for printer control or state transport.

### 2. Moonraker

Moonraker remains the printer-facing boundary for:

- printer state
- file metadata and managed paths
- event subscriptions
- future agent registration and event fan-out

### 3. Mainsail Integration

The default `v1` Mainsail integration should stay intentionally small:

- custom navigation entry in `.theme/navi.json`
- link target to `/klippyai/`
- no fork or patch required for the common install path

An optional native shell patch can still exist for advanced installs, but the heavy UI should not live in the Mainsail codebase in `v1`.

### 4. KlippyAI UI

The KlippyAI UI is served on the same origin through `/klippyai/` and owns:

- chat transcript rendering
- artifact paste and upload affordances
- diff review for proposed config changes
- approval UX for future write actions

The embedded iframe route remains available for optional launcher/drawer integrations.

## Workflow Design

### Diagnostics Graph

The first LangGraph workflow is explicit and narrow:

1. Collect context
2. Run deterministic rules
3. Call the configured LLM provider
4. Compose a typed response

The graph should remain explicit rather than becoming a freeform autonomous agent.

### Future Config Graph

The config workflow should eventually:

1. Collect current config and printer context
2. Generate candidate changes
3. Validate and normalize the proposal
4. Pause for approval
5. Apply patch or write managed include file

### Human-In-The-Loop

Any write path should require:

- diff preview
- explicit user approval
- backup creation
- rollback metadata

## Persistence

For the initial local deployment target:

- LangGraph checkpoints: SQLite
- UI sessions: in-memory for now
- future durable sessions: SQLite
- secrets: server-side local file store with tight permissions

## Security Stance

- No provider API keys in browser storage
- No silent config writes
- No unrestricted host command execution by the LLM
- Deterministic tools own all host access
- LLM outputs should be typed and validated before use

## MVP Deliverables

- Embedded chat UI
- UI session bootstrap endpoint
- Moonraker reachability probe
- deterministic rule engine for common Klipper failures
- LangGraph diagnostics pipeline
- OpenAI provider path through LangChain
- deployment skeleton for host installs

## Deferred Work

- Moonraker websocket agent registration
- authenticated credential management from the UI
- config patch generation endpoint
- safe apply endpoint with approval resume
- decision on long-term maintenance of the optional native Mainsail shell patch
- Fluidd shell integration
