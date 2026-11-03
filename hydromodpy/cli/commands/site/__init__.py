"""``hmp site`` family: declare the sites of a workspace.

Sub-actions:

- ``hmp site add NAME --outlet X Y``: declare one site in ``data/sites/catalog.csv``.
- ``hmp site import``: declare sites from a site table, a vector layer of
  outlets (``--layer``) or Hub'Eau stations (``--hubeau --bbox``).
- ``hmp site ls``: list the declared sites.
- ``hmp site show NAME``: print one declared site.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.site import add, import_sites, ls, show
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "site"
HELP: str = "Declare the sites of a workspace"

ACTIONS = (add, import_sites, ls, show)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
