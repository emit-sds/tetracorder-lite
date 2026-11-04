#!/usr/bin/env bash
# Step 1: get the container image.
#
# Pulls the published image, or builds it from Containerfile when
# TETRACORDER_BUILD=1. Safe to re-run: an image that is already here is left
# alone rather than re-pulled to confirm the same digest.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh
wait_for_docker

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[image] $IMAGE is already here"
  exit 0
fi

if [ "${TETRACORDER_BUILD:-0}" = "1" ]; then
  # Compiles specpr and Tetracorder from Fortran/ratfor, and DaVinci from the
  # vendored source in vendor/davinci; expect this to take a while on a
  # Codespaces machine.
  echo "[image] building $IMAGE from Containerfile"
  docker build $PLATFORM -f Containerfile -t "$IMAGE" .
else
  echo "[image] pulling $IMAGE (about 1.7 GB compressed)"
  # The published image is a manifest list covering amd64 and arm64, so the
  # unpinned pull gets the native one. A tag built before DaVinci was compiled
  # from source is amd64-only, though, and on an arm64 host that pull fails
  # outright -- so fall back to the amd64 image under emulation rather than
  # leaving someone stuck at step 1 with a manifest error.
  if ! docker pull $PLATFORM "$IMAGE"; then
    if [ -n "$PLATFORM" ]; then
      exit 1
    fi
    echo "[image] no image for $(uname -m) in that tag -- retrying as amd64"
    echo "[image] it will run under emulation, which is slower"
    docker pull --platform=linux/amd64 "$IMAGE"
  fi
fi
echo "[image] ready"
