"""``hmp site`` family: declare the sites of a workspace and run a site selection.

Sub-actions:

- ``hmp site add NAME --outlet X Y``: declare one site in ``data/sites/catalog.csv``.
- ``hmp site import``: declare sites from a site table, a vector layer of
  outlets (``--layer``), Hub'Eau stations (``--hubeau --bbox``) or a
  site-selection manifest (``--selection``).
- ``hmp site select FILE``: run the site selection a TOML file declares
  (``--dry-run`` validates it, ``--into-catalog`` declares the selected sites).
- ``hmp site ls``: list the declared sites.
- ``hmp site show NAME``: print one declared site.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.site import add, import_sites, ls, select, show

NAME: str = "site"
HELP: str = "Declare the sites of a workspace and run a site selection"

ACTIONS = (add, import_sites, select, ls, show)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
