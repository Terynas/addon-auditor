#!/usr/bin/env bash
# Install addon-auditor as a local Cursor plugin (MCP server + skill).
#
#   scripts/install-cursor-plugin.sh            # copy a snapshot of this checkout
#   scripts/install-cursor-plugin.sh --dev      # editable install: plugin follows this checkout
#   ADDON_AUDITOR_ROOTS=~/wow scripts/install-cursor-plugin.sh   # restrict MCP to these folders
#
# Target: ${CURSOR_PLUGINS_DIR:-~/.cursor/plugins/local}/addon-auditor. Needs Python 3.11+ (uv preferred).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CURSOR_PLUGINS_DIR:-$HOME/.cursor/plugins/local}/addon-auditor"
DEV=0
[[ "${1:-}" == "--dev" ]] && DEV=1

mkdir -p "$DEST/.cursor-plugin" "$DEST/skills"
cp "$REPO/.cursor-plugin/plugin.json" "$DEST/.cursor-plugin/plugin.json"
cp "$REPO/README.md" "$REPO/LICENSE" "$DEST/"
rm -rf "$DEST/skills/addon-auditor"
cp -r "$REPO/skills/addon-auditor" "$DEST/skills/"

if [[ -n "${ADDON_AUDITOR_ROOTS:-}" ]]; then
  ROOTS_JSON=$(printf '"ADDON_AUDITOR_ROOTS": "%s"' "$ADDON_AUDITOR_ROOTS")
else
  ROOTS_JSON=""
fi
cat > "$DEST/mcp.json" <<EOF
{
  "mcpServers": {
    "addon-auditor": {
      "command": "\${CURSOR_PLUGIN_ROOT}/.venv/bin/addon-auditor-mcp",
      "args": [],
      "env": { $ROOTS_JSON }
    }
  }
}
EOF

if command -v uv >/dev/null 2>&1; then
  uv venv --quiet --allow-existing "$DEST/.venv"
  PIP=(uv pip install --quiet --python "$DEST/.venv/bin/python")
else
  python3 -m venv "$DEST/.venv"
  PIP=("$DEST/.venv/bin/python" -m pip install --quiet)
fi
if [[ $DEV -eq 1 ]]; then
  "${PIP[@]}" -e "$REPO[mcp]"
else
  "${PIP[@]}" "$REPO[mcp]"
fi

"$DEST/.venv/bin/addon-auditor" --version
echo "Installed to $DEST"
echo "Restart Cursor (or reload MCP servers) and enable the 'addon-auditor' MCP server."
if ! "$DEST/.venv/bin/python" -c "from addon_auditor.adapters.luacheck import find_luacheck; import sys; sys.exit(0 if find_luacheck() else 1)"; then
  echo "Note: luacheck not found. Install it (luarocks install luacheck) or set ADDON_AUDITOR_LUACHECK."
fi
