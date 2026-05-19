"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy.cli.commands import (
    audit,
    calibrate,
    catalog,
    compare,
    data,
    dev,
    doctor,
    install_binaries,
    privacy,
    project,
    report,
    run,
    test,
    viz,
    workspace,
)
from hydromodpy.cli.commands import (
    index as index_cmd,
)

ALL_COMMANDS = (
    workspace,
    project,
    catalog,
    data,
    viz,
    dev,
    audit,
    privacy,
    run,
    calibrate,
    test,
    report,
    compare,
    doctor,
    install_binaries,
    index_cmd,
)

__all__ = ("ALL_COMMANDS",)
