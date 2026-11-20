"""HydroModPy CLI subcommands.

Each module exposes ``register(subparsers)`` to attach its argparse subparser
and ``run(args)`` to execute the command. ``ALL_COMMANDS`` lists the modules
in the order they should be registered on the top-level parser.

A leaf module exposes ``NAME``, ``HELP``, ``register(subparsers)``, which adds the
parser and sets ``_handler=run``, and ``run(args)``. A verb family is a sub-package
whose ``__init__.py`` carries ``NAME``, ``HELP``, an ``ACTIONS`` tuple and ``register``,
and every action module repeats the same four symbols. ``config`` and ``privacy`` are
single modules that declare their own sub-commands. A command parses its arguments,
calls one verb of ``hydromodpy.project.api``, formats the result and maps errors to exit
codes. It never writes ``import hydromodpy as hmp``, and business logic never lives in
``cli/``. A new leaf verb is a module here with its name in the import list and in
``ALL_COMMANDS``, and a new action of a family is a module listed in the ``ACTIONS``
tuple of its ``__init__.py``.
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
