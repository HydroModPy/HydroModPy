"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy.cli.commands import (
    calibrate,
    campaign,
    catalog,
    completion,
    config,
    data,
    doctor,
    example,
    export,
    install_binaries,
    lock,
    privacy,
    project,
    publish,
    report,
    run,
    site,
    spinup,
    viz,
    workspace,
)

ALL_COMMANDS = (
    workspace,
    project,
    campaign,
    example,
    catalog,
    data,
    export,
    publish,
    viz,
    config,
    lock,
    completion,
    privacy,
    run,
    calibrate,
    spinup,
    site,
    report,
    doctor,
    install_binaries,
)

__all__ = ("ALL_COMMANDS",)
