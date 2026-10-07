#!/usr/bin/env bash
# Step 4: serve the results page.
#
# A container rather than a background process: a Codespaces lifecycle command
# reaps anything it backgrounded, and a shell-owned server would also die when
# its terminal closed. --restart unless-stopped brings it back after a
# codespace stop/start without anyone having to re-run this.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh
wait_for_docker

mkdir -p "$SITE"
# The whole directory, not just index.html: it also carries the context image
# of the full granule, which cannot be generated in the codespace because the
# full granule is 1.8 GB per cube and is never downloaded there.
cp .devcontainer/page/* "$SITE/"

if container_running "$WEB_CONTAINER"; then
  echo "[results] already serving on port $PORT"
else
  docker rm -f "$WEB_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$WEB_CONTAINER" $PLATFORM \
    --restart unless-stopped \
    -p "$PORT:$PORT" \
    -v "$SITE:/site" \
    "$IMAGE" python -m http.server "$PORT" --directory /site >/dev/null
  echo "[results] serving on port $PORT ($WEB_CONTAINER)"
fi

echo
if [ -n "${CODESPACE_NAME:-}" ]; then
  # Codespaces treats CODESPACE_NAME and the forwarding domain as secrets and
  # redacts them from lifecycle logs, so a printed URL can come out as
  # "https://********-8080.********". Point at the panel instead.
  echo "  Open the PORTS panel and click the globe icon on port $PORT."
else
  echo "  Open http://localhost:$PORT"
fi
echo
