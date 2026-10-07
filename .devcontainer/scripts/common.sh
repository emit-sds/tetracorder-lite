#!/usr/bin/env bash
# Shared settings. Sourced from the repository root, so the $PWD-relative
# mounts resolve. Everything the demo writes goes under $WORK, outside the
# repository, so a run cannot dirty the tree or the build context.

WORK="${TETRACORDER_WORK:-$HOME/tetracorder-demo}"
DATA="$WORK/data"
OUTPUT="$WORK/output"
SITE="$WORK/site"
STATE="$WORK/state"

# Codespaces sets GITHUB_REPOSITORY, so a codespace opened on a fork uses that
# fork's image and scene. The fallback applies outside a codespace and is the
# only account name in the demo scripts -- update it if the home moves.
REPO="${GITHUB_REPOSITORY:-emit-sds/tetracorder-lite}"

# GHCR namespaces are lowercase; owner names need not be. The repository half
# is unused on purpose -- container.yml publishes the literal name
# "tetracorder-lite", so a renamed fork still resolves.
OWNER="$(printf '%s' "${REPO%%/*}" | tr '[:upper:]' '[:lower:]')"

# The tag is the checked-out branch, matching container.yml's
# type=ref,event=branch -- so a codespace runs the image its own branch built.
# The sed mirrors metadata-action's sanitizing (runs of invalid characters
# become one hyphen); keep the two in step or the pull asks for a tag that was
# never written. Falls back to main when there is no branch to read. Only
# branches in container.yml's push filter have an image; TETRACORDER_IMAGE
# points elsewhere.
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
case "$BRANCH" in
  "" | HEAD) TAG="main" ;;
  *) TAG="$(printf '%s' "$BRANCH" | sed 's/[^a-zA-Z0-9._-][^a-zA-Z0-9._-]*/-/g')" ;;
esac

IMAGE="${TETRACORDER_IMAGE:-ghcr.io/$OWNER/tetracorder-lite:$TAG}"

# A 300x150 window of EMIT granule emit20240626t165035 -- arid volcanic terrain,
# ~96% of pixels identified in both groups. Cut by tools/make_subset.py.
SCENE_URL="${TETRACORDER_SCENE_URL:-https://github.com/$REPO/releases/download/demo-data-v6/emit20240626t165035_300x150.tar.gz}"
PORT="${TETRACORDER_PORT:-8080}"

# Checked before the archive is unpacked; "-" skips it. Pins one specific
# archive, so a fork publishing its own scene must update this too.
SCENE_SHA256="${TETRACORDER_SCENE_SHA256:-60ed35f1285d92ba01af8c687a11634b4ae7d9825fad87d46c5314308611d9d3}"

# No --platform pin: the image is a manifest list, so docker picks the native
# architecture. Set TETRACORDER_PLATFORM to force one (e.g.
# --platform=linux/amd64). get-image.sh falls back to amd64 by itself if the tag
# turns out to be an older, amd64-only build.
PLATFORM="${TETRACORDER_PLATFORM:-}"

# Named containers: the daemon owns the long-running work, not a shell. A
# Codespaces lifecycle command reaps what it backgrounds, which killed both the
# run and the web server; a detached container survives that.
RUN_CONTAINER="${TETRACORDER_RUN_CONTAINER:-tetracorder-demo-run}"
WEB_CONTAINER="${TETRACORDER_WEB_CONTAINER:-tetracorder-demo-web}"

# Bounded docker calls. The walkthrough can start before docker-in-docker is
# up, and a call against a not-yet-answering socket blocks long enough to look
# like a hang. `timeout` is util-linux -- present on Codespaces, absent on
# macOS, where these simply run unbounded.
DOCKER_TIMEOUT="${TETRACORDER_DOCKER_TIMEOUT:-5}"
dk() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "$DOCKER_TIMEOUT" docker "$@"
  else
    docker "$@"
  fi
}

# True if the docker daemon is answering right now. Used to tell "not done yet"
# apart from "cannot tell", so the walkthrough never reports a step as pending
# when it simply could not look.
docker_ready() { dk info >/dev/null 2>&1; }

# True if the named container exists and is running.
container_running() {
  [ "$(dk inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

# Reads one value out of an ENVI header.
hdr_val() {
  sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*\(.*\)$/\1/p" "$1" | head -1 | tr -d '[:space:]\r'
}

# Bytes an ENVI cube should occupy, from its header.
envi_expected_bytes() {
  local hdr=$1 s l b dt bpe
  s=$(hdr_val "$hdr" samples); l=$(hdr_val "$hdr" lines); b=$(hdr_val "$hdr" bands)
  dt=$(hdr_val "$hdr" "data type")
  case "$dt" in
    1) bpe=1 ;; 2|12) bpe=2 ;; 3|4|13) bpe=4 ;; 5) bpe=8 ;;
    *) return 1 ;;
  esac
  [ -n "$s" ] && [ -n "$l" ] && [ -n "$b" ] || return 1
  echo $(( s * l * b * bpe ))
}

# Complete, not merely present. The archive holds rfl, rfl.hdr, uncert,
# uncert.hdr in that order, so a truncated download leaves a good reflectance
# cube and a short uncertainty one -- which only surfaces nine minutes later as
# rasterio's "Image file is too small".
verify_scene() {
  local role data hdr expected actual
  for role in rfl uncert; do
    data="$DATA/scene_$role"; hdr="$DATA/scene_$role.hdr"
    if [ ! -s "$data" ] || [ ! -s "$hdr" ]; then
      echo "[verify] missing $data or its header" >&2
      return 1
    fi
    if ! expected=$(envi_expected_bytes "$hdr"); then
      echo "[verify] could not read dimensions from $hdr" >&2
      return 1
    fi
    actual=$(wc -c < "$data" | tr -d ' ')
    if [ "$actual" -lt "$expected" ]; then
      echo "[verify] $data is truncated: $actual bytes, header implies $expected" >&2
      return 1
    fi
  done
  return 0
}

# postStartCommand can run before docker-in-docker is up, and the resulting
# failure looks like "no containers, no error". Wait rather than race.
wait_for_docker() {
  local i
  for i in $(seq 1 60); do
    docker info >/dev/null 2>&1 && return 0
    [ "$i" = 1 ] && echo "[common] waiting for the docker daemon"
    sleep 2
  done
  echo "[common] ERROR: the docker daemon did not become ready after 120s" >&2
  echo "[common] try: sudo service docker start" >&2
  return 1
}

# PYTHONUNBUFFERED: otherwise Python block-buffers to a file and the streamed
# log arrives in silent 8 KB bursts. NO_COLOR/TERM/COLUMNS ask rich for plain
# text at a fixed width instead of colour, hyperlink escapes and mid-path wraps.
env=(-e PYTHONUNBUFFERED=1 -e NO_COLOR=1 -e TERM=dumb -e COLUMNS=120)

mounts=(
  -v "$PWD/.devcontainer/config.demo.yml:/config.demo.yml:ro"
  -v "$PWD/.devcontainer/tools:/tools:ro"
  -v "$DATA:/data:ro"
  -v "$OUTPUT:/output"
  -v "$SITE:/site"
)
