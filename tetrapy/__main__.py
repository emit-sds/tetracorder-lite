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


@cli.command(help="Run tetracorder on the mounted L2A (the default container action).")
@outp
@click.option("--data-dir", default="/data", help="Directory holding the L2A ENVI scene")
@click.option("--setup/--no-setup", default=True,
              help="Run cmd-setup-tetrun against the mounted scene before running. "
                   "On by default: cmd-setup-tetrun needs the real scene to build "
                   "its run tree, so setup happens at container start (the epoch "
                   "image bakes the library + config, not the scene-specific run "
                   "tree). Use --no-setup only if the run tree was prepared already.")
def run(output, data_dir, setup):
    file = tetra.discover_l2a(data_dir)
    if setup:
        tetra.setup_tetrun(output=output, file=file)
    tetra.exec_tetrun(output=output, file=file)


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


@cli.command("convolve-epoch", help="Convolve both libraries from a text grid into the sensor-keyed outputs (build-time).")
@click.option("-s", "--sensor", default="emit_c")
@click.option("--wl", required=True)
@click.option("--fwhm", required=True)
@click.option("--units", default="nanometers")
@click.option("--spectral-lib", default="/root/tetracorder/sl1/usgs")
@click.option("--recipe-dir", default="/root/tetracorder/sl1/usgs/library06.conv")
@click.option("--cmds-dir", default="/root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds",
              help="tetracorder*.cmds dir whose restart protection is synced to the "
                   "freshly-built libraries. Pass '' to skip the restart sync.")
def convolve_epoch_cmd(sensor, wl, fwhm, units, spectral_lib, recipe_dir, cmds_dir):
    from tetrapy import epoch_config
    grid = convolve.read_wavelengths_fwhm_txt(wl, fwhm, units=units)
    slug = sensor.replace("_", "")
    std_out = f"{spectral_lib}/library06.conv/s06{slug}"
    res_out = f"{spectral_lib}/rlib06/r06{slug}"
    # standard master lives in library06.conv, research in rlib06 — build each
    # into the sensor-keyed output path the restart file references.
    convolve.build_from_recipe(
        master=f"{spectral_lib}/library06.conv/splib06b",
        recipe=f"{recipe_dir}/conv.s06{slug}.cmds", output=std_out, grid=grid)
    convolve.export_envi(std_out, f"{std_out}_envi")
    convolve.build_from_recipe(
        master=f"{spectral_lib}/rlib06/sprlb06b",
        recipe=f"{recipe_dir}/conv.r06{slug}.cmds", output=res_out, grid=grid)
    convolve.export_envi(res_out, f"{res_out}_envi")
    # Sync the restart's device-protection numbers to the freshly-built libraries
    # (reproduces the server-only AAA restart-emit step; without it specpr prompts
    # on a protection mismatch and the container silently yields zero mineral IDs).
    if cmds_dir:
        restart = epoch_config.sync_restart_protection(
            cmds_dir, sensor=sensor, res_lib=res_out, std_lib=std_out)
        click.echo(f"synced restart protection: {restart}")


@cli.command("sync-restart",
             help="Sync the sensor restart's device-protection to the baked libraries (build-time).")
@click.option("--cmds-dir", required=True, help="Path to a tetracorder*.cmds directory")
@click.option("-s", "--sensor", default="emit_c")
@click.option("--std-lib", required=True,
              help="Filesystem path to the standard library baked into the image")
@click.option("--res-lib", required=True,
              help="Filesystem path to the research library baked into the image")
def sync_restart_cmd(cmds_dir, sensor, std_lib, res_lib):
    from tetrapy import epoch_config
    restart = epoch_config.sync_restart_protection(
        cmds_dir, sensor=sensor, res_lib=res_lib, std_lib=std_lib)
    click.echo(f"synced restart protection: {restart}")


@cli.command("regen-recipe", help=convolve.build_recipe_from_master.__doc__)
@click.option("--master", required=True,
              help="Master library (splib06b / sprlb06b) to enumerate spectra from")
@click.option("--slug", required=True,
              help="Output library slug for the title suffix, e.g. r06emitc / s06emitc")
@click.option("--out", required=True, help="Path to write the conv.<slug>.cmds recipe")
@click.option("--sppad", type=int, default=4, help="Padding records per spectrum (stride = 2 + sppad)")
def regen_recipe_cmd(master, slug, out, sppad):
    rows = convolve.build_recipe_from_master(master, slug)
    convolve.write_recipe_cmds(rows, out, sppad=sppad)


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
@click.option("--std-lib", default=None,
              help="Filesystem path to the built standard library; when given, the "
                   "restart iprty protection is asserted == -(records-1) of it.")
@click.option("--res-lib", default=None,
              help="Filesystem path to the built research library; when given, the "
                   "restart iprtw protection is asserted == -(records-1) of it.")
def verify_config_cmd(cmds_dir, sensor, nchans, std_path, res_path, std_lib, res_lib):
    from tetrapy import epoch_config
    epoch_config.verify_config(cmds_dir, sensor=sensor, nchans=nchans,
                               std_path=std_path, res_path=res_path,
                               std_lib=std_lib, res_lib=res_lib)
    click.echo(f"config OK: {sensor} @ {nchans} ch")
