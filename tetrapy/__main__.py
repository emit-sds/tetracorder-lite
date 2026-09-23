import logging
import os
from pathlib import Path
from typing import Any

import click
from box import Box

from tetrapy import (
    init,
    pipeline as pl
)


Logger = logging.getLogger(__name__)
CS = dict(
    ignore_unknown_options=True,
    allow_extra_args=True,
)
Config = click.argument("config")
Section = click.option("-s", "--section", help="Subsection of the yaml to load rather than the whole file")


@click.group()
@click.version_option()
def cli() -> None:
    """
    Tetracorder-lite: containerized USGS Tetracorder for mineral identification.

    This CLI provides commands for running the complete mineral identification
    pipeline or individual stages. Each command accepts a YAML configuration file
    and optional --section and dotted --key value overrides.
    """
    pass


@cli.command(context_settings=CS)
@click.pass_context
@Config
@Section
def run(ctx: click.Context, **kwargs: Any) -> None:
    """
    Execute the full tetrapy pipeline from a YAML config.

    Runs all enabled pipeline stages in sequence: export_matrix, convolve,
    sensor, setup, tetrun, and aggregate. Each stage can be individually
    disabled via its config.{stage}.enabled flag.
    """
    c = init(ctx=ctx, **kwargs)
    pl.run(c)


@cli.command(context_settings=CS, help=pl.export_matrix.__doc__)
@click.pass_context
@Config
@Section
def export_matrix(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.export_matrix(c)


@cli.command(context_settings=CS, help=pl.convolve.__doc__)
@click.pass_context
@Config
@Section
def convolve(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.convolve(c)


@cli.command(context_settings=CS, help=pl.sensor.__doc__)
@click.pass_context
@Config
@Section
def sensor(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.sensor(c)


@cli.command(context_settings=CS, help=pl.setup.__doc__)
@click.pass_context
@Config
@Section
def setup(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.setup(c)


@cli.command(context_settings=CS, help=pl.tetrun.__doc__)
@click.pass_context
@Config
@Section
def tetrun(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.tetrun(c)


@cli.command(context_settings=CS, help=pl.aggregate.__doc__)
@click.pass_context
@Config
@Section
def aggregate(ctx: click.Context, **kwargs: Any) -> None:
    c = init(ctx=ctx, **kwargs)
    pl.aggregate(c)


@cli.command(context_settings=CS)
@click.pass_context
@Config
@Section
@click.option("--noflow", is_flag=True, help="Disables the YAML flow style which condenses lists to [a, b] notation")
def preview(ctx: click.Context, noflow=False, **kwargs: Any) -> None:
    """
    Preview the final, interpolated configuration.

    Loads and processes the configuration file (with interpolation and
    overrides) and displays it in YAML format without executing any
    pipeline stages. Useful for debugging config issues.
    """
    ctx.args += ["--log.file", "None", "--log.config", "None"]
    c = init(ctx=ctx, **kwargs)

    if noflow:
        import yaml
        Logger.info(yaml.dump(c.to_dict(), default_flow_style=None, sort_keys=False, width=120))
    else:
        Logger.info(c.to_yaml())


if __name__ == "__main__":
    cli()
