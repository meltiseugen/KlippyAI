# Mainsail Integration Assets

This directory contains both the recommended low-coupling Mainsail integration assets and an optional native-shell patch bundle.

## Recommended `v1` Integration

The default `v1` path is a supported custom navigation entry in Mainsail:

- it points to `/klippyai/`
- it opens KlippyAI in a new browser tab by default
- it does not require forking or patching Mainsail
- it survives upstream Mainsail web updates much better than direct file modifications

Use:

```bash
chmod +x ./integrations/mainsail/install-custom-nav.sh
./integrations/mainsail/install-custom-nav.sh --config-dir /home/pi/printer_data/config
```

This writes or updates:

- `/home/pi/printer_data/config/.theme/navi.json`

The example payload lives in `integrations/mainsail/navi.json.example`.

## Optional Native Shell Patch

### Intent

The native patch keeps Mainsail changes deliberately small:

- add a KlippyAI launcher button to the top bar
- mount a native Mainsail shell component
- open a right-side drawer
- bootstrap a KlippyAI UI session from `/klippyai/api/ui-sessions`
- render the embedded assistant in an iframe

The actual assistant UI and workflow logic remain in the KlippyAI service.

## Target Upstream

- Repository: `https://github.com/mainsail-crew/mainsail`
- Branch inspected: `develop`
- Commit used for this patch bundle: `6130a0aa1776a138feaab691b9e4b1334b676b79`
- Upstream package version at that commit: `2.17.0`

## Files Touched In Upstream Mainsail

- `src/App.vue`
- `src/components/TheTopbar.vue`
- `src/components/integrations/KlippyAiShell.vue`

## What The Patch Adds

### App-Level Shell Mount

`App.vue` is patched to:

- listen for a `toggle-klippyai` event from the top bar
- keep a local `showKlippyAiShell` boolean
- mount the drawer shell component

### Topbar Launcher

`TheTopbar.vue` is patched to:

- add a `KlippyAI` icon button beside the existing topbar controls
- emit `toggle-klippyai` upward

### Embedded Drawer

`KlippyAiShell.vue` is a thin Mainsail-native shell that:

- opens as a right-side drawer
- requests a UI session from `/klippyai/api/ui-sessions`
- shows a loading or error state if bootstrap fails
- loads the returned `embed_path` into an iframe

## Apply The Optional Patch

From a local Mainsail source checkout:

```bash
chmod +x ./integrations/mainsail/apply-patch.sh
./integrations/mainsail/apply-patch.sh /path/to/mainsail
```

The helper script runs `git apply --check` first, then applies the patch.

## Build And Deploy

After applying the patch in a Mainsail source checkout:

```bash
npm install
npm run build
```

Then deploy the generated Mainsail build as you normally would for your environment.

## Requirements

This shell patch assumes:

- KlippyAI is reverse-proxied on the same origin at `/klippyai/`
- `POST /klippyai/api/ui-sessions` is reachable from the Mainsail frontend
- `embed_path` points to an embeddable iframe route

## Current Limitations

- The patch does not add localization keys; the launcher label is effectively icon-first and the shell title is hardcoded `KlippyAI`.
- The patch is version-targeted to the upstream commit above and may need refreshing for future Mainsail releases.
- The patch bundle does not rebuild or deploy Mainsail automatically.
- The patch assumes the current `/klippyai` mount path.
