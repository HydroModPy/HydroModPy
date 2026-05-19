"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy.cli.commands import (
    add,
    audit,
    calibrate,
    catalog,
    compare,
    completion,
    config_cmd,
    data,
    dev,
    display,
    doctor,
    export,
    export_package,
    import_cmd,
    install_binaries,
    lock,
    manage,
    privacy,
    project,
    rank,
    report,
    run,
    schema,
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
    config_cmd,
    schema,
    run,
    calibrate,
    dev,
    display,
    report,
    export,
    export_package,
    test,
    data,
    lock,
    compare,
    add,
    import_cmd,
    doctor,
    manage,
    install_binaries,
    rank,
    completion,
    privacy,
    audit,
    viz,
    index_cmd,
)

__all__ = ("ALL_COMMANDS",)
