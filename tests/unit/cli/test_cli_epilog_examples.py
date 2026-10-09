"""Every leaf command carries an Example section, and each example line parses.

The reference pages show the epilog of a command as its example. A line that
the parser rejects, or a command with no example, is caught here instead of on
the published page. The lines are parsed, not run.
"""

from __future__ import annotations

import argparse
import re
import shlex

import pytest

from hydromodpy.cli.main import _build_parser

HEAD = re.compile(r"^Examples?:\s*$")
NAMES_OF_EXAMPLE_PROJECTS = ("cheze", "nancon", "naizin", "step4", "step5")


def _leaves(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()):
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path, parser
        return
    for action in subs:
        for name, sub in action.choices.items():
            yield from _leaves(sub, (*path, name))


def _example_lines(epilog: str | None) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in (epilog or "").splitlines():
        if HEAD.match(line):
            inside = True
        elif inside and line.startswith(" "):
            lines.append(line.strip())
        elif line.strip():
            inside = False
    return lines


def _argv(line: str) -> list[str]:
    words = shlex.split(line)
    # Drop a shell redirection such as `> out.json 2> err.log`.
    for i, word in enumerate(words):
        if word.startswith((">", "2>")):
            words = words[:i]
            break
    assert words[0] == "hmp", line
    return words[1:]


LEAVES = list(_leaves(_build_parser()))


@pytest.mark.parametrize("path", [p for p, _ in LEAVES], ids=lambda p: " ".join(p))
def test_leaf_command_has_an_example(path: tuple[str, ...]) -> None:
    parser = dict(LEAVES)[path]
    assert _example_lines(parser.epilog), f"hmp {' '.join(path)} has no Example section"


@pytest.mark.parametrize("path", [p for p, _ in LEAVES], ids=lambda p: " ".join(p))
def test_example_lines_parse(path: tuple[str, ...]) -> None:
    root = _build_parser()
    for line in _example_lines(dict(LEAVES)[path].epilog):
        argv = _argv(line)
        assert argv[: len(path)] == list(path), (
            f"{line!r} is not an example of hmp {' '.join(path)}"
        )
        try:
            root.parse_args(argv)
        except SystemExit as exc:
            pytest.fail(f"the parser rejects {line!r} (exit {exc.code})")


def test_examples_name_no_example_project() -> None:
    for path, parser in LEAVES:
        text = (parser.epilog or "").lower()
        for name in NAMES_OF_EXAMPLE_PROJECTS:
            assert name not in text, f"hmp {' '.join(path)} names an example project: {name}"
