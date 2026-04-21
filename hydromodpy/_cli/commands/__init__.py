"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy._cli.commands import (
    best,
    calibrate,
    compare,
    completion,
    config_cmd,
    data,
    delete,
    display,
    doctor,
    export,
    import_cmd,
    init,
    inspect,
    list as list_cmd,
    lock,
    new,
    run,
    schema,
    show,
    test,
    worst,
)

ALL_COMMANDS = (
    init,
    new,
    config_cmd,
    schema,
    run,
    calibrate,
    display,
    list_cmd,
    export,
    test,
    data,
    lock,
    show,
    compare,
    import_cmd,
    doctor,
    inspect,
    best,
    worst,
    delete,
    completion,
)

__all__ = ("ALL_COMMANDS",)
