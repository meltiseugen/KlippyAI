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
- `systemd`
- `nginx`
- `git`

The installer can help install:

- `python3`
- `python3-venv`
- `python3-pip`

You also need:

- an OpenAI API key if you want live LLM responses

## 2. Clone The Repo

Run on the printer host:

```bash
cd /home/<service-user>
git clone https://github.com/meltiseugen/KlippyAI.git
cd KlippyAI
chmod +x install.sh uninstall.sh
```

Example for a common `biqu` host:

```bash
cd /home/biqu
git clone https://github.com/meltiseugen/KlippyAI.git
cd KlippyAI
chmod +x install.sh uninstall.sh
```

## 3. Run The Installer

```bash
./install.sh
```

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
- write `/etc/klippyai/klippyai.env`
- write `printer_data/config/klippyai.cfg`
- detect the printer profile once and save it into `klippyai.cfg`
- write `printer_data/config/klippyai-moonraker.cfg`
- append `[include klippyai-moonraker.cfg]` to `moonraker.conf` if needed
- add `klippyai-agent` to `printer_data/moonraker.asvc`
- install and start `klippyai-agent.service`
- generate `/etc/klippyai/nginx-location.conf`
- optionally add a Mainsail nav link in `.theme/navi.json`
- write the KlippyAI runtime log to `printer_data/logs/klippyai.log`

## 5. Edit nginx

The installer does **not** patch nginx automatically.

Add this line inside the Mainsail nginx `server` block:

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

## 8. Important Files

Editable runtime config:

- `/home/<service-user>/printer_data/config/klippyai.cfg`

Server-side API key file:

- `/etc/klippyai/klippyai.env`

Moonraker include:

- `/home/<service-user>/printer_data/config/klippyai-moonraker.cfg`

Generated nginx snippet:

- `/etc/klippyai/nginx-location.conf`

KlippyAI runtime log:

- `/home/<service-user>/printer_data/logs/klippyai.log`

## 9. Change The Model Later

Edit:

- `printer_data/config/klippyai.cfg`

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
  --config-file /home/<service-user>/printer_data/config/klippyai.cfg \
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
- `[printer_geometry]`
- `[config_context]`

## 11. Runtime Behavior

KlippyAI currently:

- reads `klippy.log*`
- reads `moonraker.log*`
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
cat /home/<service-user>/printer_data/config/klippyai.cfg
cat /home/<service-user>/printer_data/config/klippyai-moonraker.cfg
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

After uninstall, remove this line from your Mainsail nginx `server` block if it is still present:

```nginx
include /etc/klippyai/nginx-location.conf;
```

Then reload nginx and restart Moonraker:

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart moonraker
```
