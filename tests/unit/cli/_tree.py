"""The parser tree of ``hmp``, walked once for every test module that reads it."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from functools import cache

from hydromodpy.cli.conventions import OldVerb
from hydromodpy.cli.main import _build_parser


@cache
def tree() -> argparse.ArgumentParser:
    """The parser of ``hmp``, built once: it imports every command module."""
    return _build_parser()


def commands(
    parser: argparse.ArgumentParser | None = None, words: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    """Yield every command of the tree, groups and leaves, by the words that name it.

    An old form stands in the tree only to refuse or forward, so it is skipped.
    """
    parser = tree() if parser is None else parser
    if isinstance(parser, OldVerb):
        return
    yield words, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from commands(child, (*words, name))


def leaves(
    parser: argparse.ArgumentParser | None = None,
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    """Yield the commands that take no action below them."""
    for words, command in commands(parser):
        if not any(isinstance(a, argparse._SubParsersAction) for a in command._actions):
            yield words, command
