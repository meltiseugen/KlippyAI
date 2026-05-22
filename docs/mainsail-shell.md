# Mainsail Integration Plan

The recommended `v1` Mainsail integration should stay deliberately thin.

## Responsibilities

- expose a supported link or button inside Mainsail
- point that link at the stable same-origin KlippyAI route
- avoid patching or forking Mainsail for the default install path

## Recommended Pattern

Use Mainsail's documented custom navigation support and add a `KlippyAI` entry in `.theme/navi.json`. The recommended entry opens KlippyAI in a new browser tab so the main Mainsail view stays intact.

Example:

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

The route at `/klippyai/` is a full-page KlippyAI shell served by the agent. It creates a UI session and loads the embedded experience internally, so Mainsail only needs to link to it.

## Why This Is The Default `v1`

- uses a documented Mainsail customization path
- survives normal Mainsail web updates better than file patching
- keeps KlippyAI independent from Mainsail release cadence
- makes a later Fluidd integration cheaper

## Installer Support

`integrations/mainsail/install-custom-nav.sh` writes or updates:

- `<printer-config>/.theme/navi.json`

The main installer can call that helper automatically.

## Optional Native Shell Patch

The repository still contains a first maintained native-shell patch bundle under `integrations/mainsail/` for advanced installs that want a topbar button and drawer.

Targeted upstream:

- repository: `mainsail-crew/mainsail`
- branch inspected: `develop`
- commit: `6130a0aa1776a138feaab691b9e4b1334b676b79`
- upstream package version: `2.17.0`

Insertion points used by the optional patch:

- `src/App.vue`
- `src/components/TheTopbar.vue`
- new file: `src/components/integrations/KlippyAiShell.vue`

The optional shell behavior in this first patch is:

- topbar launcher button
- right-side drawer shell
- `POST /klippyai/api/ui-sessions` bootstrap
- iframe mount using the returned `embed_path`

Use `integrations/mainsail/apply-patch.sh` to apply the patch to a compatible local Mainsail checkout if you choose to carry that maintenance burden.
