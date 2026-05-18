# Backlog

This backlog is organized around the current chosen architecture:

- standalone host daemon
- Moonraker underneath
- supported Mainsail custom-navigation entry in `v1`
- same-origin KlippyAI page at `/klippyai/`
- LangGraph for explicit workflow orchestration

## Milestone 0: Project Foundation

- [x] Define the initial system architecture
- [x] Scaffold the FastAPI agent service
- [x] Add a minimal embedded UI
- [x] Add LangGraph diagnostics workflow scaffolding
- [x] Add a deterministic diagnostics rule engine
- [x] Add deployment examples for `systemd` and `nginx`
- [x] Add an interactive Linux installer

## Milestone 1: Diagnostics MVP

- [x] Read recent `klippy.log` directly from the host
- [x] Read recent `moonraker.log` directly from the host
- [x] Add optional `journalctl` collection for Moonraker and Klipper services
- [x] Capture Moonraker and Klipper service status
- [ ] Add optional `journalctl` collection for broader host services
- [ ] Query core Moonraker state for server info, printer status, and config metadata
- [ ] Normalize collected context into typed artifacts before LLM calls
- [ ] Expand deterministic detections for common Klipper problems
- [ ] Return richer evidence blocks in API responses
- [ ] Add severity ranking and confidence hints
- [ ] Add unit tests for each deterministic diagnostic rule family

## Milestone 2: UI Session And Embedded Experience

- [ ] Improve the embedded chat UI to show findings, evidence, and next actions as distinct cards
- [ ] Add artifact upload support for pasted files and drag-and-drop log snippets
- [ ] Add session history persistence beyond the current in-memory session store
- [ ] Add streaming responses for long-running diagnostics
- [ ] Add explicit error states for Moonraker unavailable, missing provider config, and invalid session
- [ ] Add UI affordances for follow-up questions and drill-down analysis

## Milestone 3: Mainsail Integration

- [x] Add a stable same-origin KlippyAI page at `/klippyai/`
- [x] Add a low-coupling Mainsail custom-navigation link that opens KlippyAI
- [x] Add installer support for writing `.theme/navi.json`
- [ ] Ensure same-origin routing for `/klippyai/` behind nginx
- [ ] Validate the full-page KlippyAI route on common desktop and tablet layouts
- [ ] Improve the standalone page so it feels more at home inside the printer UI flow
- [ ] Decide whether the optional native drawer patch still earns its maintenance cost

## Milestone 4: Moonraker Integration Depth

- [ ] Implement a proper Moonraker agent registration flow
- [ ] Add Moonraker event subscriptions for printer state changes
- [ ] Add file metadata inspection through Moonraker where useful
- [ ] Add a database namespace for non-secret assistant metadata
- [ ] Define Moonraker-facing methods for session bootstrap and future notifications

## Milestone 5: Config Assistant

- [x] Add an initial config assistant workflow for managed include proposals
- [ ] Create a config analysis workflow for active printer configuration
- [ ] Detect common config mistakes such as missing includes, invalid pins, and conflicting sections
- [x] Build typed proposal objects for generated config changes
- [ ] Support managed include fragments under a KlippyAI-owned directory
- [ ] Support patch generation against existing config files
- [ ] Add config validation passes before any proposal is shown
- [ ] Add deeper feature-specific generation beyond scaffold-level proposals
- [ ] Add diff rendering in the embedded UI

## Milestone 6: Safe Apply Flow

- [ ] Add backup creation for targeted config files
- [ ] Add LangGraph `interrupt()` approval flow for user-reviewed writes
- [ ] Add resume and cancel paths after user approval decisions
- [ ] Add rollback metadata and restore command support
- [ ] Add optional `RESTART` or `FIRMWARE_RESTART` suggestion flow without automatic execution
- [ ] Keep write actions disabled by default until reviewed and tested

## Milestone 7: Provider And Credential Management

- [ ] Add secure server-side API key storage outside plain repo files
- [ ] Add UI flow for credential setup and rotation
- [ ] Add validation checks for provider credentials during setup
- [ ] Add more providers beyond OpenAI
- [ ] Add model-specific configuration and routing
- [ ] Add rate-limit and cost-safety controls

## Milestone 8: Intelligence Quality

- [ ] Add richer deterministic rules before broadening agent behavior
- [ ] Add prompt and response schemas per workflow instead of one general assistant path
- [ ] Add structured citations back to log lines and config sections
- [ ] Add recovery playbooks for recurring failure modes
- [ ] Add printer-profile awareness for common hardware classes
- [ ] Add config generation templates for high-value features such as macros, probes, and shapers

## Milestone 9: Security And Hardening

- [ ] Review local secret storage and file permissions
- [ ] Restrict host access tools to the minimum required surface
- [ ] Add redaction rules for secrets in logs and configs
- [ ] Add request size limits and artifact truncation rules
- [ ] Review nginx and service defaults for safer deployment
- [ ] Add authentication assumptions and trust-boundary docs for local deployments

## Milestone 10: Testing And Release Engineering

- [ ] Add a Linux CI pipeline for lint, type checks, and tests
- [ ] Add integration tests for installer, env generation, and service boot
- [ ] Add a smoke test for reverse-proxy routing at `/klippyai/`
- [ ] Add example artifacts for known printer failures
- [ ] Add versioning, changelog, and release notes conventions
- [ ] Add packaging guidance for a one-line remote installer in a future release

## Open Product Questions

- [ ] Should the first write-capable workflow only create managed include files, or also patch existing `printer.cfg` content?
- [ ] How much of the assistant should be accessible without any external LLM provider configured?
- [ ] Should a future native shell integration target Mainsail only, or keep Fluidd parity close behind?
- [ ] What is the right long-term secret storage method for a local appliance-style install?
- [ ] How should multi-printer hosts be modeled in the agent and UI?
- [ ] Is a true native Mainsail drawer still worth carrying after the low-coupling `/klippyai/` flow is in use?
