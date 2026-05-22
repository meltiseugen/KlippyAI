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

if [ ! -f "$ROUTER_FILE" ]; then
  printf 'OctoEverywhere router file not found: %s\n' "$ROUTER_FILE" >&2
  exit 1
fi

if [ ! -f "$UI_FILE" ]; then
  printf 'OctoEverywhere injected UI helper not found: %s\n' "$UI_FILE" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
cp "$ROUTER_FILE" "$ROUTER_FILE.klippyai-backup-$STAMP"
cp "$UI_FILE" "$UI_FILE.klippyai-backup-$STAMP"

OE_ROUTER_FILE="$ROUTER_FILE" \
OE_UI_FILE="$UI_FILE" \
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
router_file.write_text(router_text, encoding="utf-8")

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
                popup.location.replace(resolvedUrl.toString());
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
                var directUrl = new URL(klippyAiDirectHref, window.location.origin);
                directUrl.searchParams.set("_klippyai_direct", String(Date.now()));
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
ui_file.write_text(ui_text, encoding="utf-8")
PY

printf 'Patched OctoEverywhere checkout at %s\n' "$OE_ROOT"
printf '  Router file: %s\n' "$ROUTER_FILE"
printf '  UI helper:   %s\n' "$UI_FILE"
printf '  Route:       %s/ -> http://127.0.0.1:%s/\n' "$KLIPPYAI_PREFIX" "$KLIPPYAI_PORT"
printf '  Nav target:  %s\n' "$NAV_TARGET"

if [ "$RESTART_SERVICE" -eq 1 ]; then
  run_root systemctl restart "$OE_SERVICE"
  printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
fi

printf 'Next steps:\n'
printf '  1. Hard-refresh the OctoEverywhere portal.\n'
printf '  2. Open %s/ through the main OctoEverywhere printer URL.\n' "$KLIPPYAI_PREFIX"
printf '  3. If the browser still shows cached Mainsail shell content, retry in an incognito tab.\n'
