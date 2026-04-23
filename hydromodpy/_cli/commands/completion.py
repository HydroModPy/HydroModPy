"""``hmp completion`` - emit shell completion scripts."""

from __future__ import annotations

import argparse
import sys

NAME = "completion"
HELP = "Emit a shell completion script for bash, zsh, or fish"


_BASH_TEMPLATE = """\
# bash completion for hmp / hydromodpy
_hmp_complete() {
    local cur prev subcommands
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    subcommands="__SUBCOMMANDS__"
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${subcommands}" -- "${cur}") )
        return 0
    fi
    COMPREPLY=( $(compgen -f -- "${cur}") )
}
complete -F _hmp_complete hmp
complete -F _hmp_complete hydromodpy
"""

_ZSH_TEMPLATE = """\
#compdef hmp hydromodpy
_hmp() {
    local -a subcommands
    subcommands=(__SUBCOMMANDS_ZSH__)
    if (( CURRENT == 2 )); then
        _describe 'subcommand' subcommands
    else
        _files
    fi
}
_hmp "$@"
"""

_FISH_TEMPLATE = """\
# fish completion for hmp / hydromodpy
set -l __hmp_subcommands __SUBCOMMANDS__
complete -c hmp -f -n '__fish_use_subcommand' -a "$__hmp_subcommands"
complete -c hydromodpy -f -n '__fish_use_subcommand' -a "$__hmp_subcommands"
complete -c hmp -F
complete -c hydromodpy -F
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Shell flavour to emit completion for",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy._cli.commands import ALL_COMMANDS

    names = sorted({getattr(mod, "NAME", mod.__name__) for mod in ALL_COMMANDS})
    subcommands = " ".join(names)
    subcommands_zsh = " ".join(f"'{n}:{n}'" for n in names)

    if args.shell == "bash":
        text = _BASH_TEMPLATE.replace("__SUBCOMMANDS__", subcommands)
    elif args.shell == "zsh":
        text = _ZSH_TEMPLATE.replace("__SUBCOMMANDS_ZSH__", subcommands_zsh)
    else:
        text = _FISH_TEMPLATE.replace("__SUBCOMMANDS__", subcommands)

    sys.stdout.write(text)
