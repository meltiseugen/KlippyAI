#!/bin/sh

set -eu

usage() {
  cat <<'EOF'
Usage: apply-local-klippyai-route-patch.sh [options]

Patch a local OctoEverywhere checkout so the main OctoEverywhere portal can
forward /klippyai/... to the local KlippyAI backend and force a full browser
navigation from the injected frontend helper.

Options:
  --oe-root PATH          OctoEverywhere checkout root. Default: $HOME/octoeverywhere
  --klippyai-prefix PATH  Public KlippyAI prefix. Default: /klippyai
  --klippyai-port PORT    Local KlippyAI backend port. Default: 8811
  --nav-target VALUE      Sidebar click behavior: _blank or _self. Default: _blank
  --restart-service       Restart the OctoEverywhere systemd service after patching
  --service NAME          Service name to restart with --restart-service. Default: octoeverywhere
  --restore-original      Restore patched OctoEverywhere files from git before an OctoEverywhere update
  -h, --help              Show this help
EOF
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  printf 'sudo is required to run: %s\n' "$1" >&2
  exit 1
}

OE_ROOT="${HOME}/octoeverywhere"
KLIPPYAI_PREFIX="/klippyai"
KLIPPYAI_PORT="8811"
NAV_TARGET="_blank"
RESTART_SERVICE=0
OE_SERVICE="octoeverywhere"
RESTORE_ORIGINAL=0
SUSPEND_FILE="/etc/klippyai/octoeverywhere-reapply.suspended"
BACKUP_DIR="/etc/klippyai/octoeverywhere-backups"

while [ $# -gt 0 ]; do
  case "$1" in
    --oe-root)
      OE_ROOT="$2"
      shift 2
      ;;
    --klippyai-prefix)
      KLIPPYAI_PREFIX="$2"
      shift 2
      ;;
    --klippyai-port)
      KLIPPYAI_PORT="$2"
      shift 2
      ;;
    --nav-target)
      NAV_TARGET="$2"
      shift 2
      ;;
    --restart-service)
      RESTART_SERVICE=1
      shift
      ;;
    --service)
      OE_SERVICE="$2"
      shift 2
      ;;
    --restore-original|--restore)
      RESTORE_ORIGINAL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$KLIPPYAI_PREFIX" in
  "")
    KLIPPYAI_PREFIX="/klippyai"
    ;;
  /*)
    ;;
  *)
    KLIPPYAI_PREFIX="/$KLIPPYAI_PREFIX"
    ;;
esac

if [ "$KLIPPYAI_PREFIX" != "/" ]; then
  KLIPPYAI_PREFIX="${KLIPPYAI_PREFIX%/}"
fi

case "$KLIPPYAI_PORT" in
  ''|*[!0-9]*)
    printf 'Invalid --klippyai-port value: %s\n' "$KLIPPYAI_PORT" >&2
    exit 1
    ;;
esac

case "$NAV_TARGET" in
  _blank|_self)
    ;;
  *)
    printf 'Invalid --nav-target value: %s\n' "$NAV_TARGET" >&2
    exit 1
    ;;
esac

ROUTER_FILE="$OE_ROOT/moonraker_octoeverywhere/moonrakerapirouter.py"
UI_FILE="$OE_ROOT/moonraker_octoeverywhere/static/oe-ui.js"
ROUTER_TMP="$(mktemp)"
UI_TMP="$(mktemp)"
SUSPEND_TMP="$(mktemp)"

cleanup() {
  rm -f "$ROUTER_TMP" "$UI_TMP" "$SUSPEND_TMP"
}
trap cleanup EXIT

if [ ! -f "$ROUTER_FILE" ]; then
  printf 'OctoEverywhere router file not found: %s\n' "$ROUTER_FILE" >&2
  exit 1
fi

if [ ! -f "$UI_FILE" ]; then
  printf 'OctoEverywhere injected UI helper not found: %s\n' "$UI_FILE" >&2
  exit 1
fi

backup_file_to_dir() {
  source_path="$1"
  label="$2"
  backup_path="$BACKUP_DIR/$label.$STAMP"
  run_root install -d -m 755 "$BACKUP_DIR"
  run_root cp "$source_path" "$backup_path"
  printf '%s' "$backup_path"
}

if [ "$RESTORE_ORIGINAL" -eq 1 ]; then
  command -v git >/dev/null 2>&1 || {
    printf 'git is required to restore the OctoEverywhere checkout before update.\n' >&2
    exit 1
  }
  if [ ! -d "$OE_ROOT/.git" ]; then
    printf 'OctoEverywhere checkout is not a git repository: %s\n' "$OE_ROOT" >&2
    exit 1
  fi

  STAMP="$(date +%Y%m%d-%H%M%S)"
  ROUTER_BACKUP="$(backup_file_to_dir "$ROUTER_FILE" "moonrakerapirouter.py.restore-backup")"
  UI_BACKUP="$(backup_file_to_dir "$UI_FILE" "oe-ui.js.restore-backup")"
  run_root git -C "$OE_ROOT" checkout -- \
    moonraker_octoeverywhere/moonrakerapirouter.py \
    moonraker_octoeverywhere/static/oe-ui.js

  {
    printf 'KlippyAI OctoEverywhere auto-reapply is suspended for an OctoEverywhere update.\n'
    printf 'Created: %s\n' "$STAMP"
    printf 'Reapply the KlippyAI patch after updating OctoEverywhere to remove this file.\n'
  } >"$SUSPEND_TMP"
  run_root install -d -m 755 "$(dirname "$SUSPEND_FILE")"
  run_root install -m 644 "$SUSPEND_TMP" "$SUSPEND_FILE"

  printf 'Restored OctoEverywhere tracked files from git at %s\n' "$OE_ROOT"
  printf '  Router backup: %s\n' "$ROUTER_BACKUP"
  printf '  UI backup:     %s\n' "$UI_BACKUP"
  printf '  Auto-reapply suspended by: %s\n' "$SUSPEND_FILE"
  if [ "$RESTART_SERVICE" -eq 1 ]; then
    run_root systemctl restart "$OE_SERVICE"
    printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
  fi
  printf 'Next steps:\n'
  printf '  1. Update OctoEverywhere from Mainsail/Moonraker.\n'
  printf '  2. Re-run this script without --restore-original to reapply KlippyAI.\n'
  exit 0
fi

OE_ROUTER_FILE="$ROUTER_FILE" \
OE_UI_FILE="$UI_FILE" \
OE_ROUTER_OUTPUT_FILE="$ROUTER_TMP" \
OE_UI_OUTPUT_FILE="$UI_TMP" \
KLIPPYAI_PREFIX="$KLIPPYAI_PREFIX" \
KLIPPYAI_PORT="$KLIPPYAI_PORT" \
NAV_TARGET="$NAV_TARGET" \
python3 - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path


def replace_or_insert(text: str, start_marker: str, end_marker: str, block: str, anchor: str) -> str:
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.S)
    if pattern.search(text):
        return pattern.sub(block.rstrip("\n"), text)

    idx = text.find(anchor)
    if idx == -1:
        raise RuntimeError(f"Failed to find anchor: {anchor!r}")
    return text.replace(anchor, block + anchor, 1)


router_file = Path(os.environ["OE_ROUTER_FILE"])
ui_file = Path(os.environ["OE_UI_FILE"])
router_output_file = Path(os.environ["OE_ROUTER_OUTPUT_FILE"])
ui_output_file = Path(os.environ["OE_UI_OUTPUT_FILE"])
klippyai_prefix = os.environ["KLIPPYAI_PREFIX"]
klippyai_port = os.environ["KLIPPYAI_PORT"]
nav_target = os.environ["NAV_TARGET"]
klippyai_prefix_with_slash = klippyai_prefix if klippyai_prefix.endswith("/") else klippyai_prefix + "/"

router_text = router_file.read_text(encoding="utf-8")

router_init_block = f"""        # KlippyAI local route patch init start
        self.KlippyAiRootPath = "{klippyai_prefix}"
        self.KlippyAiHostAndPortStr = "127.0.0.1:{klippyai_port}"
        # KlippyAI local route patch init end

"""
router_helper_block = """    # KlippyAI local route patch helper start
    def _MapKlippyAiPathIfNeeded(self, relativeUrl:str, protocol:str) -> Optional[str]:
        if not relativeUrl:
            return None
        relativeUrlLower = relativeUrl.lower()
        klippyAiRootPathLower = self.KlippyAiRootPath.lower()
        if relativeUrlLower == klippyAiRootPathLower or relativeUrlLower.startswith(klippyAiRootPathLower + "/"):
            suffix = relativeUrl[len(self.KlippyAiRootPath):]
            if not suffix:
                suffix = "/"
            return protocol + self.KlippyAiHostAndPortStr + suffix
        return None
    # KlippyAI local route patch helper end

"""
router_map_block = """            # KlippyAI local route patch map start
            klippyAiUrl = self._MapKlippyAiPathIfNeeded(relativeUrl, protocol)
            if klippyAiUrl is not None:
                return klippyAiUrl
            # KlippyAI local route patch map end
"""

router_text = replace_or_insert(
    router_text,
    "        # KlippyAI local route patch init start",
    "        # KlippyAI local route patch init end",
    router_init_block,
    '        self.Logger.info("MoonrakerApiRouter using bound to moonraker at "+self.MoonrakerHostAndPortStr)\n',
)
router_text = replace_or_insert(
    router_text,
    "    # KlippyAI local route patch helper start",
    "    # KlippyAI local route patch helper end",
    router_helper_block,
    "    # !! Interface Function !!",
)
router_text = replace_or_insert(
    router_text,
    "            # KlippyAI local route patch map start",
    "            # KlippyAI local route patch map end",
    router_map_block,
    "            relativeUrlLower = relativeUrl.lower()\n",
)
router_output_file.write_text(router_text, encoding="utf-8")

ui_text = ui_file.read_text(encoding="utf-8")
if nav_target == "_blank":
    navigation_action = """            oe_log("Opening KlippyAI in a new tab.");
            var resolvedUrl = new URL(klippyAiHref, window.location.origin);
            resolvedUrl.searchParams.set("_klippyai_nav", String(Date.now()));
            var popup = window.open("about:blank", "_blank");
            if(popup == null)
            {
                oe_log("Browser blocked the KlippyAI popup.");
            }
            else
            {
                try
                {
                    popup.opener = null;
                }
                catch(_error)
                {
                    // Ignore cross-window opener assignment issues.
                }
                oe_open_klippyai_popup_directly(popup, resolvedUrl);
                if(typeof popup.focus === "function")
                {
                    popup.focus();
                }
            }
"""
else:
    navigation_action = """            oe_log("Forcing full navigation for KlippyAI link.");
            window.location.assign(klippyAiHref);
"""

ui_block = f"""    // KlippyAI local route patch start
    function oe_force_klippyai_full_navigation()
    {{
        if(!oe_is_connected_via_oe())
        {{
            return;
        }}

        var klippyAiHref = "{klippyai_prefix_with_slash}";
        var klippyAiHrefNoSlash = klippyAiHref.endsWith("/") ? klippyAiHref.substring(0, klippyAiHref.length - 1) : klippyAiHref;
        var klippyAiDirectHref = klippyAiHref + "direct";

        async function oe_fetch_klippyai_html(reason)
        {{
            var directUrl = new URL(klippyAiDirectHref, window.location.origin);
            directUrl.searchParams.set(reason, String(Date.now()));
            var response = await fetch(directUrl.toString(), {{
                cache: "no-store",
                credentials: "same-origin",
                headers: {{
                    "Accept": "text/html",
                    "X-KlippyAI-Route-Rescue": "1"
                }}
            }});

            if(!response.ok)
            {{
                throw new Error("KlippyAI direct route returned status " + response.status);
            }}

            var html = await response.text();
            if(html.indexOf("data-api-base=") === -1 || html.indexOf("KlippyAI") === -1)
            {{
                throw new Error("KlippyAI direct route returned non-KlippyAI HTML.");
            }}
            return html;
        }}

        async function oe_open_klippyai_popup_directly(popup, visibleUrl)
        {{
            try
            {{
                var html = await oe_fetch_klippyai_html("_klippyai_direct_open");
                try
                {{
                    popup.history.replaceState(null, "KlippyAI", visibleUrl.toString());
                }}
                catch(_historyError)
                {{
                    // Keep about:blank if the browser refuses a synthetic URL.
                }}
                popup.document.open();
                popup.document.write(html);
                popup.document.close();
            }}
            catch(error)
            {{
                oe_log("KlippyAI direct popup load failed: " + error);
                popup.location.replace(visibleUrl.toString());
            }}
        }}

        function oe_reset_klippyai_nav_state(link)
        {{
            if(!(link instanceof HTMLElement))
            {{
                return;
            }}

            var clearClasses = function(element)
            {{
                if(!(element instanceof HTMLElement))
                {{
                    return;
                }}
                if(typeof element.blur === "function")
                {{
                    element.blur();
                }}
                element.removeAttribute("aria-current");
                element.classList.remove(
                    "router-link-active",
                    "router-link-exact-active",
                    "v-list-item--active",
                    "v-item--active",
                    "primary--text",
                    "text--accent-4",
                    "focus-visible"
                );
            }};

            var listItem = link.closest(".v-list-item, li");
            var clearAll = function()
            {{
                clearClasses(link);
                clearClasses(listItem);
            }};

            clearAll();
            window.requestAnimationFrame(function()
            {{
                clearAll();
                window.requestAnimationFrame(clearAll);
            }});
            window.setTimeout(clearAll, 0);
            window.setTimeout(clearAll, 100);
        }}

        function oe_klippyai_route_needs_rescue()
        {{
            if(document.body instanceof HTMLElement && document.body.dataset && document.body.dataset.apiBase)
            {{
                return false;
            }}

            var currentPath = window.location.pathname || "";
            return currentPath === klippyAiHrefNoSlash || currentPath === klippyAiHref;
        }}

        async function oe_rescue_klippyai_route_if_needed()
        {{
            if(!oe_klippyai_route_needs_rescue())
            {{
                return;
            }}

            oe_log("Rescuing /klippyai route from Mainsail shell.");

            try
            {{
                var html = await oe_fetch_klippyai_html("_klippyai_direct");
                document.open();
                document.write(html);
                document.close();
            }}
            catch(error)
            {{
                oe_log("KlippyAI route rescue failed: " + error);
            }}
        }}

        document.addEventListener("click", function(event)
        {{
            var target = event.target;
            if(!(target instanceof Element))
            {{
                return;
            }}

            var selector = 'a[href="' + klippyAiHrefNoSlash + '"], a[href="' + klippyAiHref + '"]';
            var link = target.closest(selector);
            if(link == null)
            {{
                return;
            }}

            if(link instanceof HTMLAnchorElement)
            {{
                link.target = "{nav_target}";
                if("{nav_target}" === "_blank")
                {{
                    link.rel = "noopener noreferrer";
                }}
            }}

            event.preventDefault();
            event.stopPropagation();
            if(typeof event.stopImmediatePropagation === "function")
            {{
                event.stopImmediatePropagation();
            }}
            event.cancelBubble = true;
            event.returnValue = false;
            oe_reset_klippyai_nav_state(link);
{navigation_action.rstrip()}
        }}, true);

        oe_rescue_klippyai_route_if_needed();
    }}
    oe_force_klippyai_full_navigation();
    // KlippyAI local route patch end
"""
ui_text = replace_or_insert(
    ui_text,
    "    // KlippyAI local route patch start",
    "    // KlippyAI local route patch end",
    ui_block,
    "    oe_detect_oe_loaded_index_and_inject_helpers();\n",
)
ui_output_file.write_text(ui_text, encoding="utf-8")
PY

ROUTER_CHANGED=0
UI_CHANGED=0
if ! cmp -s "$ROUTER_FILE" "$ROUTER_TMP"; then
  ROUTER_CHANGED=1
fi
if ! cmp -s "$UI_FILE" "$UI_TMP"; then
  UI_CHANGED=1
fi

if [ "$ROUTER_CHANGED" -eq 0 ] && [ "$UI_CHANGED" -eq 0 ]; then
  printf 'OctoEverywhere checkout already matches the KlippyAI patch: %s\n' "$OE_ROOT"
  printf '  Router file: %s\n' "$ROUTER_FILE"
  printf '  UI helper:   %s\n' "$UI_FILE"
  printf '  Route:       %s/ -> http://127.0.0.1:%s/\n' "$KLIPPYAI_PREFIX" "$KLIPPYAI_PORT"
  printf '  Nav target:  %s\n' "$NAV_TARGET"
  if [ "$RESTART_SERVICE" -eq 1 ]; then
    run_root systemctl restart "$OE_SERVICE"
    printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
  fi
  if [ -f "$SUSPEND_FILE" ]; then
    run_root rm -f "$SUSPEND_FILE"
    printf 'Resumed OctoEverywhere auto-reapply by removing: %s\n' "$SUSPEND_FILE"
  fi
  exit 0
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
if [ "$ROUTER_CHANGED" -eq 1 ]; then
  ROUTER_BACKUP="$(backup_file_to_dir "$ROUTER_FILE" "moonrakerapirouter.py.patch-backup")"
  cat "$ROUTER_TMP" >"$ROUTER_FILE"
fi
if [ "$UI_CHANGED" -eq 1 ]; then
  UI_BACKUP="$(backup_file_to_dir "$UI_FILE" "oe-ui.js.patch-backup")"
  cat "$UI_TMP" >"$UI_FILE"
fi

printf 'Patched OctoEverywhere checkout at %s\n' "$OE_ROOT"
printf '  Router file: %s\n' "$ROUTER_FILE"
printf '  UI helper:   %s\n' "$UI_FILE"
printf '  Route:       %s/ -> http://127.0.0.1:%s/\n' "$KLIPPYAI_PREFIX" "$KLIPPYAI_PORT"
printf '  Nav target:  %s\n' "$NAV_TARGET"
printf '  Router edit: %s\n' "$( [ "$ROUTER_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
printf '  UI edit:     %s\n' "$( [ "$UI_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
[ "$ROUTER_CHANGED" -eq 1 ] && printf '  Router backup: %s\n' "$ROUTER_BACKUP"
[ "$UI_CHANGED" -eq 1 ] && printf '  UI backup:     %s\n' "$UI_BACKUP"

if [ "$RESTART_SERVICE" -eq 1 ]; then
  run_root systemctl restart "$OE_SERVICE"
  printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
fi

if [ -f "$SUSPEND_FILE" ]; then
  run_root rm -f "$SUSPEND_FILE"
  printf 'Resumed OctoEverywhere auto-reapply by removing: %s\n' "$SUSPEND_FILE"
fi

printf 'Next steps:\n'
printf '  1. Hard-refresh the OctoEverywhere portal.\n'
printf '  2. Open %s/ through the main OctoEverywhere printer URL.\n' "$KLIPPYAI_PREFIX"
printf '  3. If the browser still shows cached Mainsail shell content, retry in an incognito tab.\n'
