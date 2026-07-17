import os

import click

from tetrapy import tetra
from tetrapy import convolve


@click.group()
def cli():
    """tetracorder-lite CLI.

    Run USGS Tetracorder (v6) mineral identification or rebuild the convolved
    spectral library — all containerized.

    \b
    Default (no subcommand): setup + run tetracorder on the mounted input.
    """
    pass


# Shared click options
vers = click.option("-v", "--version", default="6.00a")
outp = click.option("-o", "--output", default="/output/tetracorder")
mode = click.option("-m", "--mode", default="cube")
file = click.option("-f", "--file", default="/data/r")


@cli.command(help=tetra.setup_tetrun.__doc__)
@vers
@outp
@click.option("-s", "--sensor", default="emit_c")
@mode
@file
@click.option("-g", "--geology", is_flag=True)
@click.option("-c", "--cores", type=int, default=os.cpu_count())
@click.option("-a", "--args", nargs=9, default=["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"])
@click.option("--rm", is_flag=True)
def setup(**kwargs):
    tetra.setup_tetrun(**kwargs)


@cli.command(help=tetra.exec_tetrun.__doc__)
@outp
@mode
@file
@click.option("-a", "--args", nargs=3, default=["band", "20", "gif"])
def tetrun(**kwargs):
    tetra.exec_tetrun(**kwargs)


@cli.command(help=tetra.patch_cmd_file.__doc__)
@vers
@outp
def patch(**kwargs):
    tetra.patch_cmd_file(**kwargs)


@cli.command(help="Setup then run tetracorder (the default container action).")
@click.option("-v", "--version", default="6.00a")
@outp
@click.option("-s", "--sensor", default="emit_c")
@mode
@file
@click.option("-g", "--geology", is_flag=True)
@click.option("-c", "--cores", type=int, default=os.cpu_count())
@click.option("-a", "--args", nargs=9, default=["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"])
@click.option("--rm", is_flag=True)
def run(**kwargs):
    tetra.setup_tetrun(**kwargs)
    tetra.exec_tetrun(**kwargs)


@cli.command("convolve", help=convolve.build_all.__doc__)
@file
@click.option("-o", "--output-dir", default="/output",
              help="Directory for convolved libraries (s06/r06 + ENVI)")
@click.option("--spectral-lib", default="/root/sl1/usgs/library06.conv",
              help="Directory holding master libraries (splib06b / sprlb06b). "
                   "Defaults to the masters baked into the image; override with a "
                   "mount to convolve from a different master vintage.")
@click.option("--recipe-dir", default="/spectral-lib",
              help="Directory holding conv.s06*/conv.r06* recipes (.cmds/.csv), "
                   "mounted at runtime")
@click.option("--cmds", default=None,
              help="Build a single library from this explicit recipe file "
                   "(.cmds/.csv); bypasses recipe-dir discovery")
@click.option("--master", default=None,
              help="Master library for --cmds (required when --cmds is used)")
@click.option("-o1", "--output", default=None,
              help="Output path for --cmds (required when --cmds is used)")
def convolve_cmd(file, output_dir, spectral_lib, recipe_dir, cmds, master, output):
    envi_header = f"{file}.hdr" if not file.endswith(".hdr") else file
    if cmds:
        if not (master and output):
            raise click.UsageError("--cmds requires --master and --output")
        convolve.build_from_recipe(master=master, recipe=cmds,
                                   output=output, envi_header=envi_header)
        convolve.export_envi(output, f"{output}_envi")
    else:
        convolve.build_all(
            spectral_lib_dir=spectral_lib, recipe_dir=recipe_dir,
            output_dir=output_dir, envi_header=envi_header,
        )


@cli.command("cmds2csv", help=convolve.cmds_to_csv.__doc__)
@click.argument("cmds")
@click.argument("csv")
def cmds2csv_cmd(cmds, csv):
    convolve.cmds_to_csv(cmds, csv)


@cli.command("validate", help=convolve.compare_libraries.__doc__)
@click.argument("a")
@click.argument("b")
def validate_cmd(a, b):
    convolve.compare_libraries(a, b)


@cli.command("verify-config", help="Validate the sensor-keyed config tree (build-time gate).")
@click.option("--cmds-dir", required=True, help="Path to a tetracorder*.cmds directory")
@click.option("-s", "--sensor", default="emit_c")
@click.option("--nchans", type=int, required=True, help="Channel count of the epoch")
@click.option("--std-path", default="/sl1/usgs/library06.conv/s06emitc")
@click.option("--res-path", default="/sl1/usgs/rlib06/r06emitc")
def verify_config_cmd(cmds_dir, sensor, nchans, std_path, res_path):
    from tetrapy import epoch_config
    epoch_config.verify_config(cmds_dir, sensor=sensor, nchans=nchans,
                               std_path=std_path, res_path=res_path)
    click.echo(f"config OK: {sensor} @ {nchans} ch")
