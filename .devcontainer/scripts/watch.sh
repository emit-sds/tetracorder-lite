#!/usr/bin/env bash
# Follows the demo run. This is what the auto-opened terminal task runs, so it
# has to behave sensibly at any point in the codespace's life: before the run
# container exists, while it is running, and after it has finished.
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh

printf '\n  Tetracorder demo — following the run.\n'
printf '  Ctrl-C stops watching; the run itself keeps going.\n\n'

# postStartCommand and this task race each other on a fresh codespace, and the
# task usually wins. Wait rather than reporting a container that is merely a
# few seconds away as missing.
for _ in $(seq 1 60); do
  docker inspect "$RUN_CONTAINER" >/dev/null 2>&1 && break
  sleep 2
done

if ! docker inspect "$RUN_CONTAINER" >/dev/null 2>&1; then
  echo "  No run container yet. Start one with:"
  echo "    .devcontainer/get-started.sh"
  exit 0
fi

case "$(docker inspect -f '{{.State.Status}}' "$RUN_CONTAINER" 2>/dev/null)" in
  running) docker logs -f "$RUN_CONTAINER" ;;
  exited)
    code="$(docker inspect -f '{{.State.ExitCode}}' "$RUN_CONTAINER")"
    if [ "$code" = 0 ]; then
      echo "  A previous run finished successfully. Its output is on the results page."
      echo "  Rerun with: .devcontainer/scripts/run-pipeline.sh"
    else
      echo "  The previous run exited with code $code. Last 40 lines:"
      echo
      docker logs --tail 40 "$RUN_CONTAINER" 2>&1
    fi
    ;;
  *) docker logs -f "$RUN_CONTAINER" ;;
esac
