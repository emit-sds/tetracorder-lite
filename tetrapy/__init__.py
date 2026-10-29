import logging
import warnings
from pathlib import Path

import click
from box import Box
from rasterio.errors import NotGeoreferencedWarning
from rich.console import Console
from rich.logging import RichHandler

from tetrapy.config import load

# Very spammy, just turn them off
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

# rasterio/GDAL emit a flood of DEBUG records; keep them at WARNING and up
logging.getLogger("rasterio").setLevel(logging.WARNING)

Console = Console(record=True, force_terminal=True, force_interactive=True)
Logger = logging.getLogger(__name__)


def init(config: str, section: str, ctx: click.Context) -> Box:
    """
    Initialize the tetrapy application with configuration and logging.

    Loads the YAML configuration file, applies CLI overrides, sets up logging
    handlers (console and optionally file), and optionally exports the resolved
    configuration to disk.

    Parameters
    ----------
    config : str
        Path to the config YAML file.
    section : str
        Subsection of the config to load, or a falsy value for the whole file.
    ctx : click.Context
        Click context whose extra args supply the dotted ``--key value`` overrides.

    Returns
    -------
    box.Box
        The fully resolved configuration with interpolation applied and
        overrides merged.
    """
    c = load(config, section, ctx=ctx, interp=True)

    handlers = [
        RichHandler(
            console=Console,
            rich_tracebacks=True,
            tracebacks_suppress=[click],
        )
    ]

    if c.log.file:
        file = Path(c.log.file)
        file.parent.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(file, mode="a" if c.log.append else "w")
        fh.setLevel(logging.DEBUG)

        fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
        fmt = logging.Formatter(fmt)
        fh.setFormatter(fmt)

        handlers.append(fh)

    level = c.log.get("level", "INFO").upper()
    level = getattr(logging, level)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(message)s",
        datefmt="[%X]",
    )

    config = c.log.config
    if config:
        output = Path(config)
        output.parent.mkdir(exist_ok=True, parents=True)
        c.to_yaml(filename=config)

    return c
