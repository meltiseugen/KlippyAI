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
- it does not make the OctoEverywhere checkout look clean while patched; restore
  the patch before running an OctoEverywhere update, then reapply it after the
  update

## Assumptions

- OctoEverywhere checkout path: `/home/<service-user>/octoeverywhere`
  or, on rooted Creality Nebula Pad-style layouts, `/usr/data/octoeverywhere`
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

Rooted Creality Nebula Pad example:

```bash
./integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --restart-service
```

Optional flags:

- `--klippyai-prefix /klippyai`
- `--klippyai-port 8811`
- `--nav-target _blank`
- `--service octoeverywhere`

The script writes timestamped backups under
`/etc/klippyai/octoeverywhere-backups` so the OctoEverywhere git checkout does
not get extra untracked backup files.

## Auto-Reapply After Updates

OctoEverywhere updates can replace the patched files. To install a small systemd
timer that checks the patch markers every 30 minutes and reapplies the patch
only when it is missing:

```bash
sh integrations/octoeverywhere/install-auto-reapply.sh \
  --oe-root /usr/data/octoeverywhere \
  --klippyai-prefix /klippyai \
  --klippyai-port 8811 \
  --nav-target _blank \
  --service octoeverywhere
```

Installed artifacts:

- `/usr/local/bin/klippyai-octoeverywhere-reapply`
- `/etc/systemd/system/klippyai-octoeverywhere-reapply.service`
- `/etc/systemd/system/klippyai-octoeverywhere-reapply.timer`

## Updating OctoEverywhere

This integration edits two tracked files in the OctoEverywhere checkout, so
Moonraker's update manager can report the OE repo as dirty. Before updating
OctoEverywhere, restore those files and suspend auto-reapply:

```bash
sh integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --restore-original \
  --restart-service \
  --service octoeverywhere
```

Then run the OctoEverywhere update from Mainsail/Moonraker. After it finishes,
reapply KlippyAI:

```bash
sh integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --klippyai-prefix /klippyai \
  --klippyai-port 8811 \
  --nav-target _blank \
  --restart-service \
  --service octoeverywhere
```

Reapplying removes the auto-reapply suspend marker.

## Verify

After the script restarts OctoEverywhere:

1. hard-refresh the OctoEverywhere printer portal
2. open `https://<printer>.octoeverywhere.com/klippyai/`
3. click the `KlippyAI` navigation entry from the OE-hosted Mainsail sidebar

If the browser still serves cached Mainsail shell content on the first try,
repeat the test in an incognito window.

## Rollback

Run the patch helper with `--restore-original`, then restart the OctoEverywhere
service again. The script also writes timestamped backups under
`/etc/klippyai/octoeverywhere-backups`.

## Maintenance

This patch targets OctoEverywhere's source layout as of May 2026. Restore it
before OctoEverywhere updates, reapply it after the update, and expect to
revisit it if upstream changes:

- `moonraker_octoeverywhere/moonrakerapirouter.py`
- `moonraker_octoeverywhere/static/oe-ui.js`
