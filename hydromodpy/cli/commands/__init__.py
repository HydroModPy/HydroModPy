"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy.cli.commands import (
    add,
    compare,
    completion,
    config_cmd,
    data,
    delete,
    dev,
    display,
    doctor,
    export,
    gc,
    import_cmd,
    init,
    inspect,
    install_binaries,
    lock,
    manage,
    ml,
    new,
    privacy,
    rank,
    report,
    run,
    schema,
    show,
    test,
    vacuum,
    workspace,
)
from hydromodpy.cli.commands import (
    index as index_cmd,
)
from hydromodpy.cli.commands import (
    list as list_cmd,
)

ALL_COMMANDS = (
    init,
    new,
    config_cmd,
    schema,
    run,
    dev,
    display,
    report,
    list_cmd,
    export,
    test,
    data,
    lock,
    show,
    compare,
    add,
    import_cmd,
    doctor,
    inspect,
    manage,
    install_binaries,
    rank,
    delete,
    workspace,
    completion,
    gc,
    vacuum,
    privacy,
    index_cmd,
    ml,
)

__all__ = ("ALL_COMMANDS",)
