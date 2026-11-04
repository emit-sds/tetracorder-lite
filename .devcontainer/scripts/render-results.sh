#!/usr/bin/env bash
# Re-render the results imagery from an existing run, without re-running the
# pipeline.
#
# The mineral maps are PNGs written by quicklook.py during the run, so a change
# to the rendering -- a different colour scheme, say -- does not show up by
# pulling and reloading the page. The maps have to be drawn again. The
# aggregated products are already on disk, so that takes seconds rather than
# the ten minutes a full run costs.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh
wait_for_docker

AGG="$OUTPUT/demo/aggregate/agg.nc"
if [ ! -f "$AGG" ]; then
  echo "[render] no aggregated product at $AGG" >&2
  echo "[render] run the pipeline first: .devcontainer/scripts/run-pipeline.sh" >&2
  exit 1
fi

# The page itself is a plain file copy, so refresh it at the same time.
mkdir -p "$SITE"
cp .devcontainer/page/* "$SITE/"

docker run --rm $PLATFORM "${env[@]}" "${mounts[@]}" "$IMAGE" \
  python /tools/quicklook.py \
    --rfl /data/scene_rfl \
    --agg /output/demo/aggregate/agg.nc \
    --tetracorder /output/demo/tetracorder \
    --out /site

docker run --rm $PLATFORM "${mounts[@]}" "$IMAGE" \
  chown -R "$(id -u):$(id -g)" /site >/dev/null 2>&1 || true

echo "[render] done -- reload the results page"
