#!/usr/bin/env bash
# Starts the pipeline as a detached container and, if this is a terminal,
# follows its output.
#
# The actual work is .devcontainer/tools/pipeline.sh, running inside the
# container. That is deliberate: a Codespaces lifecycle command cannot leave
# background processes behind -- anything backgrounded from postStartCommand is
# reaped when it exits -- so the docker daemon has to own the run.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh

mkdir -p "$SITE" "$OUTPUT" "$STATE"
wait_for_docker

if container_running "$RUN_CONTAINER"; then
  echo "[run] $RUN_CONTAINER is already running"
else
  # Remove a stopped container of the same name, or `docker run` refuses.
  docker rm -f "$RUN_CONTAINER" >/dev/null 2>&1 || true
  # tetracorder is verbose: mirroring its output to the container's stdout, so
  # `docker logs -f` is useful, costs ~50 MB of json-file log per run. Capped so
  # repeated reruns cannot quietly fill the codespace disk -- the complete log
  # is on disk under $SITE regardless, so nothing is actually lost.
  docker run -d --name "$RUN_CONTAINER" $PLATFORM \
    --log-opt max-size=32m --log-opt max-file=2 \
    -e PYTHONUNBUFFERED=1 -e NO_COLOR=1 -e TERM=dumb -e COLUMNS=120 \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -v "$PWD/.devcontainer/config.demo.yml:/config.demo.yml:ro" \
    -v "$PWD/.devcontainer/tools:/tools:ro" \
    -v "$DATA:/data:ro" \
    -v "$OUTPUT:/output" \
    -v "$SITE:/site" \
    "$IMAGE" bash /tools/pipeline.sh >/dev/null
  echo "[run] started $RUN_CONTAINER"
fi

if [ -t 1 ]; then
  echo "[run] following; Ctrl-C stops watching, the run keeps going"
  echo
  docker logs -f "$RUN_CONTAINER"
fi
