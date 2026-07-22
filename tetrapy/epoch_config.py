"""Validate and update the sensor-keyed Tetracorder config in an epoch image.

The DATASET and DELETED.channels files are committed, expert-curated artifacts
(see the design spec); the epoch build validates them but does not rewrite them.

The restart file is the one exception. It carries per-library "device protection"
numbers (``iprtw`` for the research/w library, ``iprty`` for the standard/y
library) that MUST equal ``-(records - 1)`` of the library they open, where
``records = filesize / 1536`` (specpr's record length; the trailing record is the
next-free slot and is not counted). The epoch build syncs these two protection
values to the libraries actually baked into the image (whether the delivered
finished libraries or an opt-in re-convolution). If they desync, specpr prints an
interactive protection WARNING that a non-interactive container silently
"continues" past, yielding zero mineral IDs.

Two build-time gates guard the silent-zero-IDs failure modes:

* protection gate — the restart's iprtw/iprty equal ``-(records - 1)`` of the
  baked libraries (see :func:`validate_restart`).
* record-alignment gate — every ``[sprlb06]``/``[splib06] <n>`` reference in the
  expert setup file (``cmd.lib.setup.*``) points at a valid data-start record in
  the baked research/standard library (see :func:`validate_record_alignment`).
  ``cmd.lib.setup`` addresses spectra by ABSOLUTE record number, so a library that
  lacks a referenced record makes tetracorder emit ``invalid input`` on that
  material and abort mineral identification. This gate catches a stale/misaligned
  library at build time instead of at runtime.
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


# A real library-record reference in cmd.lib.setup is an active "alternate library"
# selection line, e.g. ``  a SMALL:  [splib06]  7170 d``. Only the in-use SMALL
# alternate carries live record numbers; MEDIUM/LARGE are future placeholders with
# ``xxxx``. Commented lines (leading ``\#``) are notes, not selections.
_LIBREC_RE = re.compile(
    r"^\s*a\s+SMALL:\s*\[(?P<lib>sprlb06|splib06)\]\s+(?P<rec>\d+)\b", re.M)


def parse_library_record_refs(setup_text):
    """Yield (library_token, record_number) for every active SMALL selection.

    ``[sprlb06]`` selects the research/w library, ``[splib06]`` the standard/y.
    MEDIUM/LARGE placeholder (``xxxx``) and commented lines are ignored.
    """
    for line in setup_text.splitlines():
        if line.lstrip().startswith("\\#"):
            continue
        m = _LIBREC_RE.match(line)
        if m:
            yield m.group("lib"), int(m.group("rec"))


def validate_record_alignment(setup_path, *, res_lib, std_lib):
    """Raise ValueError unless every SMALL record reference is a valid data-start.

    ``cmd.lib.setup`` addresses spectra by ABSOLUTE specpr record number. Each
    ``[sprlb06] <n>`` must be a data-start in ``res_lib`` (research/w) and each
    ``[splib06] <n>`` a data-start in ``std_lib`` (standard/y). A missing/invalid
    record makes tetracorder emit ``invalid input`` on that material and produce no
    mineral IDs — this gate fails the build closed instead.
    """
    from tetrapy import convolve  # local import: convolve pulls in numpy

    libs = {}  # token -> (path, loaded records)
    for token, path in (("sprlb06", res_lib), ("splib06", std_lib)):
        if path is not None:
            libs[token] = (path, convolve.load(path))

    text = Path(setup_path).read_text()
    checked = 0
    for token, rec in parse_library_record_refs(text):
        if token not in libs:
            continue  # library not supplied for this token; skip
        path, records = libs[token]
        checked += 1
        if not (0 <= rec < len(records) and convolve._is_data_start(records[rec])):
            reason = "out of range" if rec >= len(records) else "not a data-start"
            raise ValueError(
                f"{setup_path}: [{token}] record {rec} is {reason} in {path} "
                f"({len(records)} records) — tetracorder would emit 'invalid input' "
                f"and produce no mineral IDs. The library is stale/misaligned "
                f"relative to this config."
            )
    return checked


def _resolve_setup_file(cmds_dir, sensor):
    """Return the Path to the expert cmd.lib.setup file the sensor's run uses.

    The DATASET may name it via a ``lib=`` line; otherwise the shipped default for
    this cmds tree (``cmd.lib.setup.t6.00a2``) is used. Validated to exist.
    """
    cmds = Path(cmds_dir)
    dataset = cmds / "DATASETS" / sensor
    name = None
    if dataset.exists():
        m = re.search(r"^lib=\s*([^\s#]+)", dataset.read_text(), re.M)
        if m:
            name = m.group(1)
    if name is None:
        # cmd-setup-tetrun's default: lib=cmd.lib.setup.t6.00a2
        matches = sorted(cmds.glob("cmd.lib.setup.t*a2"))
        if not matches:
            raise ValueError(f"no cmd.lib.setup.t*a2 found in {cmds}")
        return matches[-1]
    setup = cmds / name
    if not setup.exists():
        raise ValueError(f"missing setup file: {setup}")
    return setup


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
    match those libraries' record counts, AND every SMALL library-record reference
    in the expert setup file is asserted to be a valid data-start in those
    libraries (the record-alignment gate).
    """
    restart = _resolve_restart(cmds_dir, sensor)
    validate_restart(restart, nchans=nchans, iyfl=std_path, iwfl=res_path,
                     res_lib=res_lib, std_lib=std_lib)
    validate_deleted_channels(
        Path(cmds_dir) / "DELETED.channels" / f"delete_{sensor}", nchans)
    if res_lib is not None or std_lib is not None:
        setup = _resolve_setup_file(cmds_dir, sensor)
        validate_record_alignment(setup, res_lib=res_lib, std_lib=std_lib)
