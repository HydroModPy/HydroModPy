"""``hmp init`` - compatibility alias for ``hmp workspace init``."""

from __future__ import annotations

from hydromodpy.cli.commands.workspace import init_cmd

NAME = "init"
HELP = init_cmd.HELP


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("path", nargs="?", default=None, help="Workspace path")
    parser.add_argument("--path", dest="path_opt", default=None, help="Alternate flag-form")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing workspace")
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--creator-name", default=None)
    parser.add_argument("--creator-email", default=None)
    parser.set_defaults(_handler=init_cmd.run)


__all__ = ("NAME", "HELP", "register")
