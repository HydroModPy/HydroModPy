"""The theme of a render: what ``theme_rc`` says and what ``themed`` holds."""

from __future__ import annotations

import pytest

from hydromodpy.display.figure import new_subplots
from hydromodpy.display.style import RENDER_LOCK, theme_rc, themed

# ``themed`` is the only place a render writes ``rcParams``. The tests read the
# values back inside the block, then outside it, and from a second thread.


def test_an_unknown_theme_names_the_ones_there_are() -> None:
    with pytest.raises(KeyError, match="available: dark, default, print"):
        theme_rc("neon")


def test_a_figure_inside_a_block_keeps_the_background_it_was_made_with() -> None:
    with themed("dark"):
        fig, ax = new_subplots()
    assert fig.get_facecolor()[:3] == pytest.approx((0x1E / 255,) * 3)
    assert ax.get_facecolor()[:3] == pytest.approx((0x1E / 255,) * 3)


def test_the_lock_is_free_outside_a_block() -> None:
    assert RENDER_LOCK.acquire(blocking=False)
    RENDER_LOCK.release()
