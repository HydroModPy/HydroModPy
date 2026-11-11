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
    check,
    completion,
    config,
    data,
    diff,
    doctor,
    example,
    export,
    install_binaries,
    ls,
    privacy,
    project,
    publish,
    replay,
    run,
    show,
    site,
    spinup,
    stop,
    workspace,
)

ALL_COMMANDS = (
    workspace,
    project,
    campaign,
    example,
    catalog,
    data,
    ls,
    show,
    diff,
    check,
    export,
    publish,
    config,
    completion,
    privacy,
    run,
    replay,
    calibrate,
    spinup,
    stop,
    site,
    doctor,
    install_binaries,
)

__all__ = ("ALL_COMMANDS",)
