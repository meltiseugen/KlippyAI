# KlippyAI Host Install Guide

This guide is the shortest path to getting KlippyAI running on a Klipper or Kalico host that already has Moonraker and Mainsail installed.

Current runtime behavior:

- KlippyAI is `read-only`
- it can read logs, config files, and Moonraker state
- it can propose config snippets in chat
- it will **not** write printer/config files

## 1. Prerequisites

The host should already have:

- Linux
- Moonraker
- Mainsail
- `bash`
- `systemd`
- `nginx`
- `git`

The installer can help install:

- `python3` when the distro default is already Python `3.10+`
- the matching `venv` package for that interpreter, for example `python3-venv`, `python3.10-venv`, or `python3.11-venv`
- `python3-pip`

KlippyAI requires Python `3.10+`. If `python3 --version` reports `3.9` or older, run [docs/python310-install.md](docs/python310-install.md) or `./deployment/python/install-python310.sh` first, then rerun the installer.

If `bash install.sh` prints `bash: not found`, the host only has a smaller
`sh` shell. Install Bash first, then rerun `./install.sh`. On Debian/Ubuntu
hosts:

```bash
apt-get update
apt-get install -y bash
```

Some rooted appliance images, including BusyBox/OpenWrt-style environments,
may also be missing `systemd`, `nginx`, Python `venv`, or an `apt` package
manager. The current installer targets normal Klipper host images that provide
those services.

You also need:

- an OpenAI API key if you want live LLM responses

## 2. Clone The Repo

Run on the printer host:

```bash
cd /home/<service-user>
git clone https://github.com/meltiseugen/KlippyAI.git
cd KlippyAI
chmod +x install.sh uninstall.sh deployment/python/install-python310.sh
```

Example for a common `biqu` host:

```bash
cd /home/biqu
git clone https://github.com/meltiseugen/KlippyAI.git
cd KlippyAI
chmod +x install.sh uninstall.sh deployment/python/install-python310.sh
```

## 3. Run The Installer

If the host only has Python `3.9`, install Python `3.10` first:

```bash
./deployment/python/install-python310.sh
```

On CB1 and other Bullseye-era printer images, this helper usually builds Python `3.10` from source with `altinstall` so the system `python3` remains untouched.

```bash
./install.sh
```

If a previous install attempt created `.venv` with Python `3.9` or older, the updated installer will detect that and offer to recreate it.

The installer will ask for:

- Linux service user
- project checkout path
- printer data root
- Mainsail config directory
- Moonraker URL
- reverse-proxy root path
- local bind port
- local data directory
- LLM provider
- model name
- OpenAI API key if provider is `openai`
- whether to install the Mainsail navigation link

Recommended/default values:

- service user: your actual printer user, for example `biqu` or `pi`
- checkout path: `/home/<service-user>/KlippyAI`
- printer data root: `/home/<service-user>/printer_data`
- Mainsail config dir: `/home/<service-user>/printer_data/config`
- Moonraker URL: `http://127.0.0.1:7125`
- root path: `/klippyai`
- port: `8811`
- provider: `openai`
- model: `gpt-5.4-mini`

## 4. What The Installer Creates

The installer will:

- create a Python virtual environment in the repo
- install the package into that venv
- write `/etc/klippyai/klippyai.env` for the config-file path, API key, and hidden install metadata
- write `printer_data/config/klippyai/klippyai.cfg`
- detect the printer profile once and save it into `klippyai.cfg`
- write `printer_data/config/klippyai/klippyai-moonraker.cfg`
- append an include like `[include klippyai/klippyai-moonraker.cfg]` to `moonraker.conf` if needed
- add `klippyai-agent` to `printer_data/moonraker.asvc`
- install and start `klippyai-agent.service`
- generate `/etc/klippyai/nginx-location.conf`
- optionally patch the selected Mainsail nginx server block to include that snippet
- optionally add a Mainsail nav link in `.theme/navi.json`
- if `gcode_shell_command` is available, optionally create an `UPDATE_KLIPPYAI` macro plus helper script and sudoers entry
- if OctoEverywhere is installed, optionally apply the local OE `/klippyai/` route patch automatically
- write the KlippyAI runtime log to `printer_data/logs/klippyai.log`

## 5. Edit nginx

The installer can patch nginx automatically and reload it after a successful config test.

If you choose not to let the installer patch nginx, add this line inside the Mainsail nginx `server` block manually:

```nginx
include /etc/klippyai/nginx-location.conf;
```

Common file locations:

- `/etc/nginx/conf.d/mainsail.conf`
- `/etc/nginx/sites-enabled/mainsail`
- `/etc/nginx/sites-available/mainsail`

Then reload nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Restart Moonraker

Moonraker needs to reload its include file and allowed-services file:

```bash
sudo systemctl restart moonraker
```

## 7. Verify The Install

Check both services:

```bash
systemctl status klippyai-agent --no-pager
systemctl status moonraker --no-pager
```

Check KlippyAI health:

```bash
curl http://127.0.0.1:8811/healthz
```

Open the UI:

```text
http://<printer-host>/klippyai/
```

If you enabled the Mainsail nav link:

- reload the Mainsail page
- click `KlippyAI`

Optional OctoEverywhere path:

- if you want the main OctoEverywhere printer portal to serve
  `https://<printer>.octoeverywhere.com/klippyai/` without using a Shared
  Connection URL, see
  [integrations/octoeverywhere/README.md](integrations/octoeverywhere/README.md)
  and apply the local OE host patch from this repo
- if the installer detects an OctoEverywhere checkout, it can offer to apply
  that patch for you during install

## 8. Important Files

Editable runtime config:

- `/home/<service-user>/printer_data/config/klippyai/klippyai.cfg`

Optional Klipper update macro files:

- `/home/<service-user>/printer_data/config/klippyai/klippyai-macros.cfg`
- `/usr/local/bin/klippyai-self-update`
- `/etc/sudoers.d/klippyai-self-update`

Server-side API key and hidden install metadata:

- `/etc/klippyai/klippyai.env`

Moonraker include:

- `/home/<service-user>/printer_data/config/klippyai/klippyai-moonraker.cfg`

Generated nginx snippet:

- `/etc/klippyai/nginx-location.conf`

KlippyAI runtime log:

- `/home/<service-user>/printer_data/logs/klippyai.log`

## 9. Change The Model Later

Edit:

- `printer_data/config/klippyai/klippyai.cfg`

Change:

```ini
[llm]
llm_provider = openai
openai_model = gpt-5.4-mini
```

Then restart:

```bash
sudo systemctl restart klippyai-agent
```

## 10. Rerun Printer Profile Detection

If the detected profile is wrong or you want to refresh it:

```bash
/home/<service-user>/KlippyAI/.venv/bin/klippyai-detect-profile \
  --config-file /home/<service-user>/printer_data/config/klippyai/klippyai.cfg \
  --moonraker-url http://127.0.0.1:7125 \
  --printer-data-root /home/<service-user>/printer_data \
  --overwrite
```

Then restart:

```bash
sudo systemctl restart klippyai-agent
```

You can also manually edit these sections in `klippyai.cfg`:

- `[printer_identity]`
- `[printer_capabilities]`
- `[config_context]`

If this host still has an older `[printer_geometry]` section in `klippyai.cfg`, remove that section before restarting `klippyai-agent`.

## 11. Runtime Behavior

KlippyAI currently:

- reads current `.log` files under `printer_data/logs`
- sends only the configured last lines from each collected log file
- writes its own runtime log to `printer_data/logs/klippyai.log`
- reads current config files
- reads Moonraker state
- reads `systemctl` and `journalctl` data for Klipper and Moonraker
- proposes config snippets in chat

KlippyAI currently does **not**:

- write printer config files
- patch `printer.cfg`
- apply config proposals automatically

## 12. Troubleshooting

If the service does not start:

```bash
systemctl status klippyai-agent --no-pager
journalctl -u klippyai-agent -n 200 --no-pager
tail -n 200 /home/<service-user>/printer_data/logs/klippyai.log
```

If Moonraker integration does not show up:

```bash
systemctl status moonraker --no-pager
journalctl -u moonraker -n 200 --no-pager
```

Check the generated files:

```bash
cat /etc/klippyai/klippyai.env
cat /home/<service-user>/printer_data/config/klippyai/klippyai.cfg
cat /home/<service-user>/printer_data/config/klippyai/klippyai-moonraker.cfg
cat /home/<service-user>/printer_data/moonraker.asvc
```

Check nginx:

```bash
sudo nginx -t
```

## 13. Uninstall

To remove KlippyAI:

```bash
cd /home/<service-user>/KlippyAI
./uninstall.sh
```

Then reload nginx if needed and restart Moonraker:

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart moonraker
```
