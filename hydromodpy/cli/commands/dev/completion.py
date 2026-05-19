"""``hmp dev completion`` - emit rich shell completion scripts.

The generated scripts cover:

- Top-level subcommands and families (`hmp <TAB>`).
- Sub-actions of every family (`hmp project <TAB>`, `hmp catalog <TAB>`, ...).
- Long flags exposed by each leaf parser (`hmp run --<TAB>`).

The walk relies on the family ``ACTIONS`` attribute and on a one-shot
introspection of each ``register(subparsers)`` to harvest the long-form
flags. The introspection runs at script-emission time, so completion
scripts pick up changes after every ``hmp dev completion <shell> > out``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

NAME: str = "completion"
HELP: str = "Emit a shell completion script for bash, zsh, or fish"


_BASH_TEMPLATE = """\
# bash completion for hmp / hydromodpy
_hmp_complete() {
    local cur prev cmd action top_level
    cur="${COMP_WORDS[COMP_CWORD]}"
    top_level="__TOP_LEVEL__"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${top_level}" -- "${cur}") )
        return 0
    fi

    cmd="${COMP_WORDS[1]}"
    case "${cmd}" in
__FAMILY_CASES__
        *)
            local flags="${cur}"
            local cmd_flags
            cmd_flags=$(_hmp_flags_for "${cmd}")
            if [[ "${cur}" == -* && -n "${cmd_flags}" ]]; then
                COMPREPLY=( $(compgen -W "${cmd_flags}" -- "${cur}") )
            else
                COMPREPLY=( $(compgen -f -- "${cur}") )
            fi
            ;;
    esac
}

_hmp_flags_for() {
    case "$1" in
__FLAG_CASES__
        *) echo "" ;;
    esac
}

complete -F _hmp_complete hmp
complete -F _hmp_complete hydromodpy
"""


_ZSH_TEMPLATE = """\
#compdef hmp hydromodpy
_hmp() {
    local -a top_level
    top_level=(__TOP_LEVEL_ZSH__)

    if (( CURRENT == 2 )); then
        _describe 'subcommand' top_level
        return
    fi

    local cmd="${words[2]}"
    case "${cmd}" in
__FAMILY_CASES_ZSH__
        *)
            _files
            ;;
    esac
}
_hmp "$@"
"""


_FISH_TEMPLATE = """\
# fish completion for hmp / hydromodpy
set -l __hmp_top_level __TOP_LEVEL__
complete -c hmp -f -n '__fish_use_subcommand' -a "$__hmp_top_level"
complete -c hydromodpy -f -n '__fish_use_subcommand' -a "$__hmp_top_level"

__FISH_FAMILIES__

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


def _collect_top_level_and_actions() -> tuple[list[str], dict[str, list[str]]]:
    """Walk ``ALL_COMMANDS`` and harvest top-level names plus family actions."""
    from hydromodpy.cli.commands import ALL_COMMANDS

    top: list[str] = []
    family_actions: dict[str, list[str]] = {}
    for mod in ALL_COMMANDS:
        name = getattr(mod, "NAME", mod.__name__.rsplit(".", 1)[-1])
        top.append(name)
        actions = getattr(mod, "ACTIONS", None)
        if actions:
            family_actions[name] = sorted(
                {getattr(a, "NAME", a.__name__.rsplit(".", 1)[-1]) for a in actions}
            )
    return sorted(top), family_actions


def _flags_for_command(mod: object) -> list[str]:
    """Run ``mod.register`` against a throwaway parser and harvest long flags."""
    parser = argparse.ArgumentParser(add_help=False)
    sub = parser.add_subparsers(dest="_dummy_action")
    try:
        sub_parser = mod.register(sub)  # type: ignore[attr-defined]
    except Exception:
        return []
    flags: set[str] = set()
    for action in getattr(sub_parser, "_actions", []):
        for option in getattr(action, "option_strings", ()):
            if option.startswith("--"):
                flags.add(option)
    return sorted(flags)


def _all_command_flags() -> dict[str, list[str]]:
    """Map top-level command name to its long flags."""
    from hydromodpy.cli.commands import ALL_COMMANDS

    payload: dict[str, list[str]] = {}
    for mod in ALL_COMMANDS:
        name = getattr(mod, "NAME", mod.__name__.rsplit(".", 1)[-1])
        flags = _flags_for_command(mod)
        if flags:
            payload[name] = flags
    return payload


def _bash_family_cases(family_actions: dict[str, list[str]]) -> str:
    blocks: list[str] = []
    for family, actions in family_actions.items():
        actions_str = " ".join(actions)
        blocks.append(
            f"""        {family})
            if [[ ${{COMP_CWORD}} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "{actions_str}" -- "${{cur}}") )
            else
                COMPREPLY=( $(compgen -f -- "${{cur}}") )
            fi
            ;;"""
        )
    return "\n".join(blocks)


def _bash_flag_cases(command_flags: dict[str, list[str]]) -> str:
    blocks: list[str] = []
    for name, flags in command_flags.items():
        flags_str = " ".join(flags)
        blocks.append(f'        {name}) echo "{flags_str}" ;;')
    return "\n".join(blocks)


def _zsh_family_cases(family_actions: dict[str, list[str]]) -> str:
    blocks: list[str] = []
    for family, actions in family_actions.items():
        actions_str = " ".join(f"'{a}:{a}'" for a in actions)
        blocks.append(
            f"""        {family})
            local -a actions
            actions=({actions_str})
            if (( CURRENT == 3 )); then
                _describe 'action' actions
            else
                _files
            fi
            ;;"""
        )
    return "\n".join(blocks)


def _fish_family_completions(family_actions: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for family, actions in family_actions.items():
        actions_str = " ".join(actions)
        for binary in ("hmp", "hydromodpy"):
            lines.append(
                f"complete -c {binary} -f -n '__fish_seen_subcommand_from {family}' -a "
                f'"{actions_str}"'
            )
    return "\n".join(lines)


def _top_level_for_bash(names: Iterable[str]) -> str:
    return " ".join(names)


def _top_level_for_zsh(names: Iterable[str]) -> str:
    return " ".join(f"'{n}:{n}'" for n in names)


def run(args: argparse.Namespace) -> None:
    top, family_actions = _collect_top_level_and_actions()
    command_flags = _all_command_flags()

    if args.shell == "bash":
        text = (
            _BASH_TEMPLATE.replace("__TOP_LEVEL__", _top_level_for_bash(top))
            .replace("__FAMILY_CASES__", _bash_family_cases(family_actions))
            .replace("__FLAG_CASES__", _bash_flag_cases(command_flags))
        )
    elif args.shell == "zsh":
        text = _ZSH_TEMPLATE.replace("__TOP_LEVEL_ZSH__", _top_level_for_zsh(top)).replace(
            "__FAMILY_CASES_ZSH__", _zsh_family_cases(family_actions)
        )
    else:
        text = _FISH_TEMPLATE.replace("__TOP_LEVEL__", _top_level_for_bash(top)).replace(
            "__FISH_FAMILIES__", _fish_family_completions(family_actions)
        )

    sys.stdout.write(text)
