#!/usr/bin/env bash
# Re-export the vendored DaVinci source from ASU's Subversion server. Only for
# moving to a new upstream revision -- the build uses the committed src/ tree
# and never touches the network. See VENDOR.md.
#
# Usage:  ./refresh.sh [revision]
set -euo pipefail

REV="${1:-19810}"
URL="https://oss.mars.asu.edu/svn/davinci/davinci/trunk"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Everything upstream carries except dv_tests (612 MB of test imagery) and
# win32, neither referenced by the Linux build. Adding one here is deliberate:
# record why.
KEEP=(config contrib docs lib libltdl moddvmagick modules tests vicar)

# svn:externals are not followed by a targeted export, so they are named here.
# iomedley is DaVinci's image-IO layer and the build fails without it; `library`
# (~320 MB of Mars data) and `iomod_isis3` are excluded by our configure flags.
EXTERNALS=(iomedley)

# ASU's certificate chain is not in the usual trust stores, so svn fails with
# "issuer is not trusted". Running in a container keeps that workaround, and the
# svn dependency, off the host.
docker run --rm -v "$HERE:/vendor" -w /vendor "${DAVINCI_REFRESH_IMAGE:-ubuntu:22.04}" bash -euc "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq subversion ca-certificates >/dev/null
  T='--non-interactive --trust-server-cert-failures=unknown-ca,cn-mismatch,expired,not-yet-valid,other'
  rm -rf src && mkdir -p src

  # svn export has no exclude, so naming what we want is the only way to leave
  # dv_tests and win32 behind.
  svn export -q \$T -r '$REV' --depth files '$URL' src/.toplevel
  mv src/.toplevel/* src/ 2>/dev/null || true
  rmdir src/.toplevel

  for d in ${KEEP[*]}; do
    svn export -q \$T -r '$REV' '$URL'/\$d src/\$d
  done

  # Externals carry their own revisions and cannot be pinned to \$REV; HEAD is
  # what upstream's own build resolves.
  for d in ${EXTERNALS[*]}; do
    svn export -q \$T "https://oss.mars.asu.edu/svn/davinci/\$d/trunk" src/\$d
    svn info \$T "https://oss.mars.asu.edu/svn/davinci/\$d/trunk" > src/\$d/.svn-info
    # Autotools cache from upstream's tree; regenerated on demand, 1.7 MB.
    rm -rf src/\$d/autom4te.cache
  done

  svn info \$T -r '$REV' '$URL' > src/.svn-info
"

echo "exported r$REV -> $HERE/src  ($(du -sh "$HERE/src" | cut -f1), $(find "$HERE/src" -type f | wc -l | tr -d ' ') files)"
echo "update the revision and date in VENDOR.md, then commit."
