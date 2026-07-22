import os
import re
import shutil
from pathlib import Path

import subprocess


def setup_tetrun(
    version="6.00a",
    output="/output/tetracorder",
    sensor="emit_c",
    mode="cube",
    file="/data/r",
    geology=False,
    cores=os.cpu_count(),
    args=["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"],
    rm=False,
    **_
):
    """\
    Calls the tetracorder cmd-setup-tetrun script

    \b
    Parameters
    ----------
    version : str, default="6.00a"
        Tetracorder version to use
    output : str, default="/output/tetracorder"
        Output directory. Must not exist
    sensor : str, default="emit_c"
        Sensor to use
    mode : str, default="cube"
        Tetracorder mode, either "cube" or "singlespectrum"
    file : str, default="/data/r"
        File to process
    geology : bool, default=False
        If v6 tetracorder, enables geology. Defaults to nogeology
    cores : int, default=os.cpu_count()
        Cores to set in TETNCPU.txt
    args : list, default=["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"]
        Arguments to pass to cmd-setup-tetrun
    rm : bool, default=False
        Removes the output directory to do a clean setup
    """
    exists = Path(output).exists()
    if rm and exists:
        shutil.rmtree(output)

    assert not exists, "cmd-setup-tetrun requires the output directory to not exist"

    cmd = [
        f"/t1/tetracorder.cmds/tetracorder{version}.cmds/cmd-setup-tetrun",
        output,
        sensor,
        mode,
        file,
        *args
    ]

    # Fail loud: a non-zero cmd-setup-tetrun must abort, not silently leave a
    # half-built run tree that yields zero mineral IDs later.
    subprocess.run(cmd, check=True)

    # Remove erroneous 'time' command in the script
    path = Path(output) / "cmd.runtet"
    if path.exists():
        path.write_text(
            path.read_text().replace("time", "")
        )

    # v6 cmd file needs to set the geology parameter
    if "6" in version:
        path = Path(f"{output}/cmds.start.t{version}")

        if path.exists():
            lines = path.read_text().splitlines()

            geo = "geology" if geology else "nogeology"
            for i, line in enumerate(lines):
                if line.startswith("mode"):
                    lines.insert(i, geo)
                    break

            path.write_text("\n".join(lines) + "\n")

    if cores:
        path = Path(f"{output}/TETNCPU.txt")
        if path.exists():
            path.write_text(str(cores))

    print("\nAlternatively, use `tetrapy tetrun` to execute with defaults")


def exec_tetrun(
    output="/output/tetracorder",
    mode="cube",
    file="/data/r",
    args=["band", "20", "gif"],
    **_
):
    """\
    Calls the tetracorder cmd.runtet script

    \b
    Parameters
    ----------
    output : str, default="/output/tetracorder"
        Output directory
    mode : str, default="cube"
        Tetracorder mode, either "cube" or "singlespectrum"
    file : str, default="/data/r"
        File to process
    args : list, default=["band", "20", "gif"]
        Arguments to pass to cmd.runtet
    """
    cmd = [
        "./cmd.runtet",
        mode,
        file
    ]

    # Fail loud on a non-zero cmd.runtet: the container contract is fail-closed, so
    # a runtet error must surface as a non-zero container exit rather than an
    # apparently-successful run with no mineral-ID output.
    subprocess.run(cmd, cwd=output, check=True)


def discover_l2a(data_dir="/data"):
    """Return the extensionless path of the single ENVI reflectance scene in data_dir.

    A scene is an ENVI ``.hdr`` with a matching binary sidecar. Tetracorder's
    ``cmd-setup-tetrun`` / ``cmd.runtet`` want the path WITHOUT the ``.hdr`` and
    require the binary to exist at that extensionless path (it checks ``[ -f ]``
    on the exact path). EMIT L2A ships as ``<stem>.img`` + ``<stem>.hdr``, so when
    only the ``.img`` sidecar is present we expose the binary at the extensionless
    ``<stem>`` path (via symlink) so tetracorder finds it.
    """
    data_dir = Path(data_dir)
    hdrs = sorted(p for p in data_dir.glob("*.hdr"))
    scenes = []
    for h in hdrs:
        stem = h.with_suffix("")
        img = stem.with_suffix(".img")
        if stem.exists():
            scenes.append(str(stem))
        elif img.exists():
            # Tetracorder wants the binary at the extensionless stem path; EMIT
            # ships it as .img. Link stem -> .img so `[ -f <stem> ]` succeeds.
            try:
                stem.symlink_to(img.name)
            except FileExistsError:
                pass
            except OSError as e:
                raise OSError(
                    f"cannot expose {img.name} at extensionless path {stem.name} "
                    f"(is {data_dir} writable?): {e}"
                )
            scenes.append(str(stem))
    if not scenes:
        raise FileNotFoundError(f"no ENVI scene (.hdr + sidecar) found in {data_dir}")
    if len(scenes) > 1:
        raise ValueError(f"expected one scene in {data_dir}, found {len(scenes)}: {scenes}")
    return scenes[0]


def parse_variables(file: str) -> dict[str, float | tuple[float, ...]]:
    """
    Parse ==[NAME] value... definitions from a command file.

    Parameters
    ----------
    text : str
        Input text

    Returns
    -------
    dict[str, float | tuple[float, ...]]
        Mapping of variable names to either a float or tuple of floats.
        If a variable is defined multiple times, the last definition wins.
    """
    text = Path(file).read_text()

    pattern = re.compile(r"^==\[(?P<name>[^\]]+)\]\s*(?P<values>[-+0-9.eE\s]+)", re.MULTILINE)

    variables = {}
    for match in pattern.finditer(text):
        values = tuple(map(float, match["values"].split()))
        variables[match["name"]] = values[0] if len(values) == 1 else values

    return variables


def parse_variables(file: str) -> dict[str, str]:
    """Parse ==[NAME] value... definitions from a command file.

    If a variable is defined multiple times, the last definition wins.
    """
    text = Path(file).read_text()

    pattern = re.compile(
        r"^==\[(?P<name>[^\]]+)\]\s*(?P<values>[-+0-9.eE\s]+)",
        re.MULTILINE,
    )

    return {
        match["name"]: match["values"].strip()
        for match in pattern.finditer(text)
    }


def patch_cmd_file(output, version):
    """
    Creates a patched version of the expert command file to be compatible with the EMIT
    l2b scripts
    """
    cmd = "cmd.lib.setup"
    ver = f"t{version}2"

    output = Path(output)
    variables = parse_variables(output / f"{cmd}.variables")

    text = Path(output / f"{cmd}.{ver}").read_text()

    # Fix variable substitutions
    text = re.sub(
        r"\[([^\]]+)\]",
        lambda m: variables.get(m[1], m[0]),
        text,
    )

    # Remove all instances of TITLE= that aren't a title line
    text = re.sub(
        r"(?m)^(?!\\#[-=]+.*TITLE=).*?TITLE=",
        "",
        text,
    )

    Path(output / f"{cmd}.{ver}.patched").write_text(text)
