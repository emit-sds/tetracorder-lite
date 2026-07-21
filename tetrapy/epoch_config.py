"""Validate and update the sensor-keyed Tetracorder config in an epoch image.

The DATASET and DELETED.channels files are committed, expert-curated artifacts
(see the design spec); the epoch build validates them but does not rewrite them.

The restart file is the one exception. It carries per-library "device protection"
numbers (``iprtw`` for the research/w library, ``iprty`` for the standard/y
library) that MUST equal ``-(records - 1)`` of the library they open, where
``records = filesize / 1536`` (specpr's record length; the trailing record is the
next-free slot and is not counted). Because the epoch stage re-convolves the
libraries — which can change the record count relative to the committed masters —
the build rewrites these two protection values to match the freshly-built
libraries. This reproduces what the server-only
``AAA.make.new.instrument.convolved.*.sh`` scripts did per epoch: emit a restart
whose protection matches the library just built. If they desync, specpr prints an
interactive protection WARNING that a non-interactive container silently
"continues" past, yielding zero mineral IDs.
"""
import re
from pathlib import Path

RECLEN = 1536  # specpr record length in bytes


def records_in(lib_path):
    """Number of specpr records in a library = filesize / 1536.

    Raises ValueError if the file is not a whole number of records (which would
    mean it is truncated or not a specpr library).
    """
    size = Path(lib_path).stat().st_size
    if size % RECLEN != 0:
        raise ValueError(
            f"{lib_path}: size {size} is not a multiple of {RECLEN} "
            f"(not a valid specpr library?)"
        )
    return size // RECLEN


def _protection_for(lib_path):
    """specpr device-protection value for a built library: -(records - 1)."""
    return -(records_in(lib_path) - 1)


def _set_restart_int(text, key, value):
    """Replace ``key=<int>`` in a restart file, preserving column width + comment.

    Restart lines look like ``iprtw=         -1343  # device protection w``.
    We keep everything up to ``=``, right-justify the new value in the same field
    width, and keep the trailing comment. Raises ValueError if the key is absent.
    """
    pat = re.compile(rf"^({re.escape(key)}=)(\s*)(-?\d+)(.*)$", re.M)
    m = pat.search(text)
    if not m:
        raise ValueError(f"restart file has no {key}= line to rewrite")
    field_w = len(m.group(2)) + len(m.group(3))  # preserve original column width
    new = f"{m.group(1)}{str(value).rjust(field_w)}{m.group(4)}"
    return text[: m.start()] + new + text[m.end():]


def rewrite_restart_protection(restart_path, *, res_lib, std_lib):
    """Set the restart's iprtw/iprty to match the freshly-built libraries.

    ``iprtw`` (research/w device) <- -(records(res_lib) - 1)
    ``iprty`` (standard/y device) <- -(records(std_lib) - 1)

    Idempotent: rewriting an already-correct restart is a no-op on content.
    """
    restart_path = Path(restart_path)
    text = restart_path.read_text()
    text = _set_restart_int(text, "iprtw", _protection_for(res_lib))
    text = _set_restart_int(text, "iprty", _protection_for(std_lib))
    restart_path.write_text(text)


def parse_deleted_channels(text):
    """Expand USGS DELETED.channels range syntax to a sorted unique channel list.

    Tokens: ``NtM`` (inclusive range), bare integers. A trailing ``c``/``C`` on
    the last token, lone ``C`` lines, and ``#`` comments are ignored.
    """
    channels = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line in ("c", "C"):
            continue
        for tok in line.split():
            t = tok.rstrip("cC")
            if not t:
                continue
            m = re.fullmatch(r"(\d+)t(\d+)", t)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                channels.update(range(lo, hi + 1))
            elif t.isdigit():
                channels.add(int(t))
            else:
                raise ValueError(f"unparseable DELETED.channels token: {tok!r}")
    return sorted(channels)


def validate_deleted_channels(path, nchans):
    """Raise ValueError unless the file parses to a non-empty in-range channel set."""
    chans = parse_deleted_channels(Path(path).read_text())
    if not chans:
        raise ValueError(f"{path}: no channels parsed")
    lo, hi = chans[0], chans[-1]
    if lo < 1 or hi > nchans:
        raise ValueError(f"{path}: channel {lo}..{hi} outside [1, {nchans}]")


def _restart_value(text, key):
    m = re.search(rf"^{re.escape(key)}=\s*([^\s#]+)", text, re.M)
    return m.group(1) if m else None


def validate_restart(path, *, nchans, iyfl, iwfl, res_lib=None, std_lib=None):
    """Raise ValueError unless the restart file matches the epoch/library wiring.

    When ``res_lib``/``std_lib`` are given, also assert the device-protection
    numbers equal ``-(records - 1)`` of those built libraries — a fail-closed
    gate against the desync that silently produces zero mineral IDs.
    """
    text = Path(path).read_text()
    got_n = _restart_value(text, "nchans")
    if got_n is None or int(got_n) != nchans:
        raise ValueError(f"{path}: nchans={got_n}, expected {nchans}")
    for key, want in (("iyfl", iyfl), ("iwfl", iwfl)):
        got = _restart_value(text, key)
        if got != want:
            raise ValueError(f"{path}: {key}={got!r}, expected {want!r}")
    for key, lib in (("iprtw", res_lib), ("iprty", std_lib)):
        if lib is None:
            continue
        want = _protection_for(lib)
        got = _restart_value(text, key)
        if got is None or int(got) != want:
            raise ValueError(
                f"{path}: {key}={got!r} but library {lib} has "
                f"{records_in(lib)} records -> protection must be {want} "
                f"(specpr will prompt/continue and produce no mineral IDs)"
            )


def _resolve_restart(cmds_dir, sensor):
    """Return the restart Path referenced by the sensor's DATASET, validated to exist."""
    cmds = Path(cmds_dir)
    dataset = cmds / "DATASETS" / sensor
    if not dataset.exists():
        raise ValueError(f"missing DATASET: {dataset}")
    m = re.search(r"^restart=\s*([^\s#]+)", dataset.read_text(), re.M)
    if not m:
        raise ValueError(f"{dataset}: no restart= line")
    # restart_files/ is a sibling of DATASETS/ under the cmds root, not nested
    # inside it (verified against tetracorder6.00a.cmds).
    restart = cmds / "restart_files" / m.group(1)
    if not restart.exists():
        raise ValueError(f"missing restart file: {restart}")
    return restart


def sync_restart_protection(cmds_dir, *, sensor, res_lib, std_lib):
    """Rewrite the sensor's restart protection to match the built libraries.

    Resolves the restart via the DATASET's ``restart=`` line, then delegates to
    :func:`rewrite_restart_protection`. Returns the restart Path touched.
    """
    restart = _resolve_restart(cmds_dir, sensor)
    rewrite_restart_protection(restart, res_lib=res_lib, std_lib=std_lib)
    return restart


def verify_config(cmds_dir, *, sensor, nchans, std_path, res_path,
                  res_lib=None, std_lib=None):
    """Validate the sensor-keyed config tree under a tetracorder*.cmds directory.

    When ``res_lib``/``std_lib`` (paths to the built research/standard libraries)
    are supplied, the restart's device-protection numbers are also asserted to
    match those libraries' record counts.
    """
    restart = _resolve_restart(cmds_dir, sensor)
    validate_restart(restart, nchans=nchans, iyfl=std_path, iwfl=res_path,
                     res_lib=res_lib, std_lib=std_lib)
    validate_deleted_channels(
        Path(cmds_dir) / "DELETED.channels" / f"delete_{sensor}", nchans)
