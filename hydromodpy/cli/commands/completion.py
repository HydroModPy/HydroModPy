"""``hmp completion`` - print the shell completion script for ``hmp`` and ``hydromodpy``.

The script is the one ``argcomplete`` writes. It asks ``hmp`` itself for the
commands and the flags at each press of the tab key, so it follows the parser
and keeps no list of commands. In bash or zsh, load it with
``eval "$(hmp completion bash)"``. In fish, pipe it to ``source``.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import workspace_parser

NAME: str = "completion"
HELP: str = "Print a shell completion script for bash, zsh, or fish"

_EPILOG = """\
Examples:
  hmp completion bash
  hmp completion fish

In bash or zsh, load the script in the current shell with
eval "$(hmp completion bash)", or add that line to ~/.bashrc or ~/.zshrc.
In fish, pipe it to source. The script asks hmp for the commands each time
you press TAB, so it follows the commands that exist.
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(reads_none=True)],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Shell flavour to print completion for",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import argcomplete

    sys.stdout.write(argcomplete.shellcode(["hmp", "hydromodpy"], shell=args.shell))
