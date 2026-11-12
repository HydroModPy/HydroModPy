"""Guard tests for the ``-q/-v/--debug`` console verbosity flags.

Every leaf of the commands that do work offers the shorthands, and applies the
resolved level before doing any work.
"""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.core.logging import DEFAULT_VERBOSITY, current_verbosity, set_verbosity
from tests.unit.cli._tree import leaves

VERBOSITY_OPTIONS = {"--verbosity", "-q", "--quiet", "-v", "--verbose", "--debug"}

# What takes the verbosity flags, every leaf of it. A family that prints only a
# line or two (site, example, lock) leaves the level to HMP_VERBOSITY.
WITH_VERBOSITY = (
    "ls",
    "show",
    "diff",
    "data",
    "catalog",
    "project",
    "campaign",
    "export",
    "spinup",
    "run",
    "calibrate",
)


LEAVES = {" ".join(words): parser for words, parser in leaves() if words[0] in WITH_VERBOSITY}


@pytest.fixture(autouse=True)
def _restore_verbosity():
    """Every test in this module may flip the process-wide console level."""
    before = current_verbosity()
    yield
    set_verbosity(before)


@pytest.mark.parametrize("verb", sorted(LEAVES))
def test_a_leaf_offers_the_shorthands(verb: str) -> None:
    """A static check: most of these commands need a workspace or an index to run."""
    parser = LEAVES[verb]
    opts = {flag for action in parser._actions for flag in action.option_strings}
    assert not VERBOSITY_OPTIONS - opts, f"{verb} is missing {VERBOSITY_OPTIONS - opts}"
