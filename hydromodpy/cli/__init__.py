"""HydroModPy command-line interface package.

The CLI is organized as a thin argparse dispatcher (:mod:`hydromodpy.cli.main`)
plus one module per subcommand under :mod:`hydromodpy.cli.commands`. Each
command file exposes a ``register(subparsers)`` helper that attaches the
subparser and a ``run(args)`` handler invoked by the dispatcher.

The entry point is :func:`hydromodpy.cli.main.main`, named there and nowhere
else: the package imports nothing at import time, so ``python -m
hydromodpy.cli.main`` runs the module once and warns about nothing.
"""
