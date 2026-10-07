#!/usr/bin/env bash
# Removes the demo's containers and output so .devcontainer/get-started.sh begins again.
# Leaves the image and the downloaded scene alone -- those are the slow parts
# and there is no reason to fetch them twice.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh

docker rm -f "$RUN_CONTAINER" "$WEB_CONTAINER" >/dev/null 2>&1 || true
echo "[reset] removed the demo containers"

if [ -d "$OUTPUT/demo" ] || [ -d "$SITE" ]; then
  # Tetracorder's output tree is written by root inside the container, so it
  # cannot be removed from out here without help.
  docker run --rm $PLATFORM -v "$OUTPUT:/output" -v "$SITE:/site" "$IMAGE" \
    sh -c 'rm -rf /output/demo /output/.stale-* /site/*' >/dev/null 2>&1 || true
  echo "[reset] cleared previous results"
fi
echo "[reset] run .devcontainer/get-started.sh to begin again"
