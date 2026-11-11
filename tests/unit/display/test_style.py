"""The theme of a render: what ``theme_rc`` says and what ``themed`` holds."""

from __future__ import annotations

import threading

import matplotlib as mpl
import pytest

from hydromodpy.display.figure import new_figure, new_subplots
from hydromodpy.display.style import RENDER_LOCK, THEMES, get_theme, theme_rc, themed

# ``themed`` is the only place a render writes ``rcParams``. The tests read the
# values back inside the block, then outside it, and from a second thread.


@pytest.mark.parametrize("name", sorted(THEMES))
def test_theme_rc_carries_the_preset(name: str) -> None:
    theme = get_theme(name)
    rc = theme_rc(name)
    assert rc["axes.facecolor"] == theme.background
    assert rc["text.color"] == theme.foreground
    assert rc["grid.alpha"] == theme.grid_alpha
    assert rc["font.size"] == theme.font_size_base
    assert list(rc["axes.prop_cycle"].by_key()["color"]) == theme.palette


def test_theme_rc_writes_nothing() -> None:
    before = dict(mpl.rcParams)
    theme_rc("dark")
    assert dict(mpl.rcParams) == before


def test_an_unknown_theme_names_the_ones_there_are() -> None:
    with pytest.raises(KeyError, match="available: dark, default, print"):
        theme_rc("neon")


@pytest.mark.parametrize(
    ("name", "extra", "key", "expected"),
    [
        ("dark", None, "axes.facecolor", "#1e1e1e"),
        ("dark", {"font.size": 20}, "font.size", 20),
        ("dark", {"font.size": 20}, "axes.facecolor", "#1e1e1e"),
        (None, {"font.size": 20}, "font.size", 20),
    ],
)
def test_themed_puts_the_values_in_force_for_the_block(name, extra, key, expected) -> None:
    before = dict(mpl.rcParams)
    with themed(name, extra):
        assert mpl.rcParams[key] == expected
    assert dict(mpl.rcParams) == before


def test_themed_without_a_name_keeps_the_style_in_force() -> None:
    with themed("dark"), themed() as inner:
        assert inner is None
        assert mpl.rcParams["axes.facecolor"] == "#1e1e1e"


def test_themed_gives_back_the_resolved_theme() -> None:
    with themed("print") as theme:
        assert theme is get_theme("print")


def test_themed_gives_the_values_back_after_an_error() -> None:
    before = dict(mpl.rcParams)
    with pytest.raises(RuntimeError), themed("dark"):
        raise RuntimeError("a figure failed")
    assert dict(mpl.rcParams) == before


def test_a_figure_inside_a_block_keeps_the_background_it_was_made_with() -> None:
    with themed("dark"):
        fig, ax = new_subplots()
    assert fig.get_facecolor()[:3] == pytest.approx((0x1E / 255,) * 3)
    assert ax.get_facecolor()[:3] == pytest.approx((0x1E / 255,) * 3)


def test_a_nested_block_does_not_wait_for_the_outer_one() -> None:
    # A figure that sets its own style inside a render holds the lock already.
    with themed("dark"), themed(extra={"font.size": 17}):
        assert mpl.rcParams["font.size"] == 17
    assert mpl.rcParams["font.size"] != 17


def test_a_second_thread_waits_for_the_render_and_meets_the_default_style() -> None:
    seen: list[str] = []
    started = threading.Event()

    def other() -> None:
        started.set()
        with themed():
            seen.append(mpl.rcParams["axes.facecolor"])

    with themed("dark"):
        thread = threading.Thread(target=other)
        thread.start()
        started.wait(5)
        thread.join(0.2)
        assert thread.is_alive(), "the second render waits for the lock"
    thread.join(5)
    assert seen == [mpl.rcParamsDefault["axes.facecolor"]]


def test_the_lock_is_free_outside_a_block() -> None:
    assert RENDER_LOCK.acquire(blocking=False)
    RENDER_LOCK.release()


@pytest.mark.parametrize(
    ("make", "n_axes"),
    [
        (lambda: new_subplots(figsize=(4, 3), dpi=80, constrained_layout=True), 1),
        (lambda: new_subplots(2, 3, sharey=True, squeeze=False, figsize=(6, 3)), 6),
        (lambda: new_subplots(1, 2, gridspec_kw={"width_ratios": [3, 1]}), 2),
    ],
)
def test_new_subplots_builds_the_grid_without_pyplot(make, n_axes) -> None:
    from matplotlib import _pylab_helpers

    fig, axes = make()
    assert len(fig.axes) == n_axes
    assert axes is not None
    assert not _pylab_helpers.Gcf.get_all_fig_managers()


def test_new_figure_takes_the_figure_keywords_and_keeps_its_dpi_on_save(tmp_path) -> None:
    fig = new_figure(figsize=(2, 1), dpi=50)
    fig.subplots().plot([0, 1])
    target = tmp_path / "out.png"
    fig.savefig(target, dpi=100)
    header = target.read_bytes()[16:24]
    assert int.from_bytes(header[:4], "big") == 200
    assert int.from_bytes(header[4:], "big") == 100
