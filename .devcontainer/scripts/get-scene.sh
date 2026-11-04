#!/usr/bin/env bash
# Step 2: get the sample scene, and prove it arrived intact before using it.
#
# Three independent checks, because a bad scene is expensive: the pipeline runs
# for nine minutes before aggregate opens the uncertainty cube and rasterio
# rejects it with "Image file is too small".
#
#   1. the archive's SHA-256, before anything is extracted
#   2. tar's own exit status on extraction -- previously unchecked, so a failed
#      extraction proceeded silently and left short files behind
#   3. each cube's byte count against the dimensions in its own ENVI header
set -euo pipefail
cd "$(dirname "$0")/../.."
source .devcontainer/scripts/common.sh

mkdir -p "$DATA" "$OUTPUT" "$SITE" "$STATE"

sha_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# Printed whenever something goes wrong, so a failure report carries the facts
# needed to explain it instead of prompting another round trip.
diagnose() {
  echo "[scene] --- diagnostics ---" >&2
  echo "[scene] disk:" >&2
  df -h "$DATA" 2>&1 | sed 's/^/[scene]   /' >&2
  echo "[scene] contents of $DATA:" >&2
  ls -la "$DATA" 2>&1 | sed 's/^/[scene]   /' >&2
}

# A stamp recording which archive the staged scene came from. verify_scene only
# checks each cube's size against its own header, so a scene left over from an
# earlier release verifies perfectly well and would be reused for ever -- the
# demo would keep running yesterday's tile after the scene was replaced. Compare
# the checksum too, and re-fetch when it differs.
STAMP="$DATA/.scene-sha256"

if verify_scene 2>/dev/null && [ "$(cat "$STAMP" 2>/dev/null)" = "$SCENE_SHA256" ]; then
  echo "[scene] already present and complete"
  exit 0
fi
if verify_scene 2>/dev/null; then
  echo "[scene] a different scene is staged here; replacing it"
  rm -f "$DATA"/*_rfl "$DATA"/*_rfl.hdr "$DATA"/*_uncert "$DATA"/*_uncert.hdr \
        "$DATA"/scene_* "$STAMP" 2>/dev/null || true
fi

archive="$STATE/scene.tar.gz"

for attempt in 1 2 3; do
  echo "[scene] downloading (attempt $attempt of 3)"
  rm -f "$archive"

  # To a file, not piped into tar: a stream that dies mid-pipe leaves tar
  # having already written partial files, which is the failure this step exists
  # to prevent.
  if ! curl -fL --retry 3 --retry-delay 5 -o "$archive" "$SCENE_URL"; then
    echo "[scene] download failed" >&2
    continue
  fi

  got="$(wc -c < "$archive" | tr -d ' ')"
  echo "[scene] downloaded $got bytes"

  if [ "$SCENE_SHA256" != "-" ]; then
    actual_sha="$(sha_of "$archive")"
    if [ "$actual_sha" != "$SCENE_SHA256" ]; then
      echo "[scene] checksum mismatch -- the download is not the published archive" >&2
      echo "[scene]   expected $SCENE_SHA256" >&2
      echo "[scene]   got      $actual_sha" >&2
      continue
    fi
    echo "[scene] checksum ok"
  fi

  if ! tar tzf "$archive" >/dev/null 2>"$STATE/tar.err"; then
    echo "[scene] archive will not list:" >&2
    sed 's/^/[scene]   /' "$STATE/tar.err" >&2
    continue
  fi

  # Checked, unlike before. A full disk or a read error here is the difference
  # between a good archive and short files on disk.
  if ! tar xzf "$archive" -C "$DATA" 2>"$STATE/tar.err"; then
    echo "[scene] extraction failed:" >&2
    sed 's/^/[scene]   /' "$STATE/tar.err" >&2
    diagnose
    continue
  fi
  rm -f "$archive" "$STATE/tar.err"

  # An archive built by bsdtar on macOS carries the extended attributes of each
  # file as a separate "._name" AppleDouble entry. macOS tar hides those when
  # listing -- it understands them natively -- but GNU tar on Linux materialises
  # them as real 163-byte files sitting right next to the data. A glob of
  # "*_uncert" then matches both, and which one came first was down to directory
  # order: the real file here, the sidecar on Linux. Deleted rather than merely
  # skipped, so nothing downstream can trip over them either.
  find "$DATA" -maxdepth 1 -name '._*' -delete 2>/dev/null || true

  # config.demo.yml refers to the scene as scene_rfl / scene_uncert. The
  # archive keeps the granule's real name for provenance, so link the two
  # together rather than renaming and losing it.
  for role in rfl uncert; do
    for suffix in "" ".hdr"; do
      # -name "*_rfl" does not match "*_rfl.hdr", so each of the four files
      # should match exactly once. Requiring exactly one, rather than taking
      # the first of however many, is the point: silently picking one of two
      # candidates is what linked scene_uncert to a 163-byte sidecar and cost
      # a nine-minute run to discover.
      matches="$(find "$DATA" -maxdepth 1 -name "*_${role}${suffix}" \
                      ! -name "scene_*" ! -name ".*" | sort)"
      count="$(printf '%s' "$matches" | grep -c . || true)"
      if [ "$count" != 1 ]; then
        echo "[scene] ERROR: expected exactly one *_${role}${suffix}, found $count:" >&2
        printf '%s\n' "$matches" | sed 's/^/[scene]   /' >&2
        diagnose
        exit 1
      fi
      ln -sfn "$(basename "$matches")" "$DATA/scene_${role}${suffix}"
    done
  done

  if verify_scene; then
    printf '%s' "$SCENE_SHA256" > "$STAMP"
    echo "[scene] ready"
    exit 0
  fi
  echo "[scene] the extracted scene is still incomplete" >&2
  diagnose
done

echo "[scene] ERROR: could not obtain a complete scene after 3 attempts" >&2
exit 1
