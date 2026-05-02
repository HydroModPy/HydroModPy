"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.
"""

from __future__ import annotations

from hydromodpy.cli.commands import (
    add,
    catalog,
    compare,
    compare_methods,
    completion,
    config_cmd,
    data,
    delete,
    dev,
    display,
    doctor,
    export,
    import_cmd,
    init,
    inspect,
    install_binaries,
    lock,
    manage,
    new,
    rank,
    report,
    run,
    schema,
    show,
    test,
    workspace,
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
    catalog,
    display,
    report,
    list_cmd,
    export,
    test,
    data,
    lock,
    show,
    compare,
    compare_methods,
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
)

__all__ = ("ALL_COMMANDS",)
