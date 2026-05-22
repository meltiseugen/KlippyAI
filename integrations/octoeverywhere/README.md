# OctoEverywhere Host Patch

This integration is an unsupported local patch for an existing Klipper
OctoEverywhere checkout. It is intended for hosts where:

- the main OctoEverywhere printer portal still serves Mainsail or Fluidd
- `Shared Connection` URLs are not desired for KlippyAI
- KlippyAI is already installed locally and reachable behind nginx at `/klippyai/`

What the patch does:

- extends OctoEverywhere's Moonraker-side relative-path router so requests for
  `/klippyai` and `/klippyai/...` are forwarded directly to the local KlippyAI
  backend on `127.0.0.1:8811`
- patches OctoEverywhere's injected frontend helper so the `KlippyAI` nav item
  bypasses the Mainsail SPA/router and can open KlippyAI in either the current
  tab or a new tab

What it does not do:

- it does not patch Mainsail itself
- it does not add a second officially supported frontend to OctoEverywhere
- it does not survive OctoEverywhere source updates automatically

## Assumptions

- OctoEverywhere checkout path: `/home/<service-user>/octoeverywhere`
- KlippyAI backend port: `8811`
- KlippyAI public prefix: `/klippyai`

If your host differs, pass explicit arguments to the helper script.

If `install.sh` detects an OctoEverywhere checkout, it can offer to run this
helper automatically.

## Apply

From the KlippyAI checkout on the host:

```bash
chmod +x integrations/octoeverywhere/apply-local-klippyai-route-patch.sh
./integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /home/<service-user>/octoeverywhere \
  --restart-service
```

Optional flags:

- `--klippyai-prefix /klippyai`
- `--klippyai-port 8811`
- `--nav-target _blank`
- `--service octoeverywhere`

The script writes timestamped backups next to the patched OctoEverywhere files.

## Verify

After the script restarts OctoEverywhere:

1. hard-refresh the OctoEverywhere printer portal
2. open `https://<printer>.octoeverywhere.com/klippyai/`
3. click the `KlippyAI` navigation entry from the OE-hosted Mainsail sidebar

If the browser still serves cached Mainsail shell content on the first try,
repeat the test in an incognito window.

## Rollback

Restore the timestamped backup files created by the script, then restart the
OctoEverywhere service again.

## Maintenance

This patch targets OctoEverywhere's source layout as of May 2026. Reapply it
after OctoEverywhere updates, and expect to revisit it if upstream changes:

- `moonraker_octoeverywhere/moonrakerapirouter.py`
- `moonraker_octoeverywhere/static/oe-ui.js`
