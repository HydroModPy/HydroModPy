"""``hmp dev test`` adds a ``--basetemp`` only when ``PYTEST_ADDOPTS`` holds none."""

from __future__ import annotations

import pytest

from hydromodpy.cli.commands.dev.test import pytest_addopts_declares_basetemp


@pytest.mark.parametrize(
    ("addopts", "declared"),
    [
        ("--basetemp=x", True),
        ("-q --basetemp=x", True),
        ("-q --basetemp x", True),
        ("-q\t--basetemp", True),
        ("-q --basetemporary=x", False),
        ("-q", False),
        ("", False),
    ],
)
def test_a_basetemp_anywhere_in_the_options_is_seen(addopts: str, declared: bool) -> None:
    assert pytest_addopts_declares_basetemp(addopts) is declared
