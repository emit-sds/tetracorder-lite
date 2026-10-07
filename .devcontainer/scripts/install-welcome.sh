#!/usr/bin/env bash
# Adds the welcome banner to ~/.bashrc, once.
#
# Runs as onCreateCommand, which Codespaces also runs during a prebuild, so the
# banner is baked in. Nothing secret is involved, which is the requirement for
# anything that runs there.
set -euo pipefail
cd "$(dirname "$0")/../.."

MARK="# tetracorder-demo-welcome"
RC="$HOME/.bashrc"

if grep -qF "$MARK" "$RC" 2>/dev/null; then
  echo "[welcome] already installed in $RC"
  exit 0
fi

# The repository's real path, resolved now rather than hardcoded: Codespaces
# uses /workspaces/<repo>, but a clone elsewhere or a renamed folder would not
# match, and the banner would silently never appear.
REPO="$(pwd -P)"

# Guarded on an interactive shell so it cannot interfere with scripts, and on
# the script still existing so a stale line cannot break a future shell.
cat >> "$RC" <<RCEOF

# tetracorder-demo-welcome
if [ -n "\$PS1" ] && [ -x "$REPO/.devcontainer/scripts/welcome.sh" ]; then
  "$REPO/.devcontainer/scripts/welcome.sh"
fi
RCEOF
echo "[welcome] installed in $RC"
