"""HydroModPy command-line interface package.

The CLI is organised as a thin argparse dispatcher (:mod:`hydromodpy._cli.main`)
plus one module per subcommand under :mod:`hydromodpy._cli.commands`. Each
command file exposes a ``register(subparsers)`` helper that attaches the
subparser and a ``run(args)`` handler invoked by the dispatcher.
"""

from __future__ import annotations

from hydromodpy._cli.main import main

__all__ = ("main",)
