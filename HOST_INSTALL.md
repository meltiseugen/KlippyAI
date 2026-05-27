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
`sh` shell. Install Bash first, then rerun `./install.sh`.

```bash
apt-get update && apt-get install -y bash  # Debian/Ubuntu hosts
opkg update && opkg install bash           # Entware/OpenWrt-style hosts
apk add bash                               # Alpine hosts
```

Some rooted appliance images, including BusyBox/OpenWrt-style environments,
may also be missing `systemd`, `nginx`, Python `venv`, or a package manager.
The current installer targets normal Klipper host images that provide those
services. If the host has no `apt-get`, `opkg`, or `apk`, install Entware or use
a normal Klipper host instead.

On rooted Creality/Nebula-style images, first check what is actually available:

```sh
for command_name in bash apt-get opkg apk systemctl nginx python3 pip3 git; do
  command -v "$command_name" >/dev/null 2>&1 && echo "$command_name: yes" || echo "$command_name: no"
done
python3 --version
python3 -m venv --help >/dev/null 2>&1 && echo "python venv: yes" || echo "python venv: no"
```

On rooted Creality Nebula Pad-style layouts, the printer data root is usually:

- printer data root: `/usr/data/printer_data`
- Mainsail config dir: `/usr/data/printer_data/config`
- related host data: `/usr/data/mainsail`, `/usr/data/moonraker`, `/usr/data/nginx`
- OctoEverywhere checkout, when installed: `/usr/data/octoeverywhere`

The installer detects `/usr/data/printer_data` automatically when it exists. If
you are prompted for the printer data root on one of these pads, use
`/usr/data/printer_data`.

If `systemctl` is `no`, the guided installer is not currently supported on that
host even if Bash can be installed.

If `opkg` is `yes`, `bash` is `no`, and `nginx` is `no`, install the missing
shell and proxy packages first:

```sh
opkg update
opkg install bash
opkg install nginx-ssl || opkg install nginx
```

If Python is `3.10+` but `python venv` is `no`, the installer can now fall back
to the Python `virtualenv` package. If prompted, let it install `virtualenv`
with pip, or install it manually first:

```sh
python3 -m pip install --user virtualenv
```

The default dependency set avoids Rust-backed packages that are awkward on these
pads. If an earlier install failed while building `uuid-utils`, `ormsgpack`,
`maturin`, or `pydantic-core`, remove the partial virtual environment and rerun
the installer after updating the checkout. The installer also asks Python
packages with optional speedups to use pure-Python fallbacks where possible.

```sh
cd /root/KlippyAI
rm -rf .venv
./install.sh
```

Some rooted images have `systemctl` but do not pre-create
`/etc/systemd/system`. The installer creates that directory before writing the
`klippyai-agent.service` unit.

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

- `/usr/data/nginx/nginx.conf`
- `/etc/nginx/conf.d/mainsail.conf`
- `/etc/nginx/sites-enabled/mainsail`
- `/etc/nginx/sites-available/mainsail`

Some Creality nginx configs contain separate Fluidd and Mainsail `server`
blocks in one file. In that layout, make sure the include is inside the
Mainsail server block too, usually the one with `listen 80` and
`root /usr/data/mainsail`.

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
- on rooted Creality Nebula Pad-style layouts, the OctoEverywhere checkout is
  often `/usr/data/octoeverywhere`; pass that as `--oe-root` if applying the
  patch manually
- if you choose the OctoEverywhere patch in the installer, it can also install
  a small systemd timer that reapplies the patch after future OE updates replace
  the patched files
- because the patch edits two tracked files in the OctoEverywhere checkout,
  Moonraker can show the OE repo as dirty before an OE update. Restore the patch
  first, update OctoEverywhere, then reapply the patch.

Manual auto-reapply timer install:

```bash
sh integrations/octoeverywhere/install-auto-reapply.sh \
  --oe-root /usr/data/octoeverywhere \
  --klippyai-prefix /klippyai \
  --klippyai-port 8811 \
  --nav-target _blank \
  --service octoeverywhere
```

Prepare for an OctoEverywhere update:

```bash
sh integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --restore-original \
  --restart-service \
  --service octoeverywhere
```

After the OctoEverywhere update finishes, reapply KlippyAI:

```bash
sh integrations/octoeverywhere/apply-local-klippyai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --klippyai-prefix /klippyai \
  --klippyai-port 8811 \
  --nav-target _blank \
  --restart-service \
  --service octoeverywhere
```

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

## 11. Optional UPDATE_KLIPPYAI Macro

The installer offers this macro when it detects Klipper/Kalico
`gcode_shell_command` support. If it finds a Klipper/Kalico checkout but the
extension is missing, it can offer to install `gcode_shell_command.py` from the
KIAUH extension asset first, then install the macro. This is opt-in because it
allows Klipper macros to run host shell commands.

On rooted Creality images, that support may live outside the service user's
home, so check it directly:

```bash
find /usr/data /root /opt /usr/local /usr/share -maxdepth 6 \
  -type f -path '*/klippy/extras/gcode_shell_command.py' 2>/dev/null
```

If the macro is installed, it writes:

- `/usr/local/bin/klippyai-self-update`
- `/usr/data/printer_data/config/klippyai/klippyai-macros.cfg`
- an include in `/usr/data/printer_data/config/printer.cfg`
- `/etc/sudoers.d/klippyai-self-update` only when Klipper does not run as root

When Klipper runs as root, the macro calls `/usr/local/bin/klippyai-self-update`
directly and does not require `sudo`.

Manual install on a rooted Nebula Pad:

```bash
cd /root/KlippyAI
sh integrations/klipper/install-update-macro.sh \
  --install-dir /root/KlippyAI \
  --install-user root \
  --config-dir /usr/data/printer_data/config \
  --root-config /usr/data/printer_data/config/printer.cfg \
  --install-gcode-shell-command \
  --restart-klipper
```

## 12. Runtime Behavior

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

## 13. Troubleshooting

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

If clicking the Mainsail `KlippyAI` button opens a blank Mainsail page, check
whether `/klippyai/` is falling through to Mainsail instead of KlippyAI:

```bash
curl http://127.0.0.1:8811/healthz
curl http://127.0.0.1/klippyai/healthz
grep -R "klippyai\|nginx-location" /usr/data/nginx /etc/nginx 2>/dev/null
```

The first two commands should return JSON. If `/klippyai/healthz` returns
Mainsail HTML, add `include /etc/klippyai/nginx-location.conf;` inside the
active Mainsail nginx `server` block, then reload nginx.

## 14. Uninstall

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
