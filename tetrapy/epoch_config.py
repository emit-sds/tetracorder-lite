"""Validate the sensor-keyed Tetracorder config baked into an epoch image.

The DATASET, restart, and DELETED.channels files are committed, expert-curated
artifacts (see the design spec). The epoch build does NOT rewrite them — it
validates that they are internally consistent with the delivery's channel count
and the baked convolved-library outputs.
"""
import re
from pathlib import Path


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


def validate_restart(path, *, nchans, iyfl, iwfl):
    """Raise ValueError unless the restart file matches the epoch/library wiring."""
    text = Path(path).read_text()
    got_n = _restart_value(text, "nchans")
    if got_n is None or int(got_n) != nchans:
        raise ValueError(f"{path}: nchans={got_n}, expected {nchans}")
    for key, want in (("iyfl", iyfl), ("iwfl", iwfl)):
        got = _restart_value(text, key)
        if got != want:
            raise ValueError(f"{path}: {key}={got!r}, expected {want!r}")


def verify_config(cmds_dir, *, sensor, nchans, std_path, res_path):
    """Validate the sensor-keyed config tree under a tetracorder*.cmds directory."""
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
    validate_restart(restart, nchans=nchans, iyfl=std_path, iwfl=res_path)
    validate_deleted_channels(cmds / "DELETED.channels" / f"delete_{sensor}", nchans)
