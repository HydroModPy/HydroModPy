"""Tests of the static matplotlib template."""

from __future__ import annotations

import threading

import matplotlib
import pytest

from hydromodpy.display import static as st
from hydromodpy.display.theme import get_theme

THEME = get_theme("default")
CALLER_RC = {
    "font.family": "serif",
    "text.color": "red",
    "lines.linewidth": 5,
    "image.cmap": "jet",
    "axes.prop_cycle": matplotlib.cycler(color=["red"]),
    "figure.constrained_layout.h_pad": 0.2,
}


def draw():
    fig = st.new_figure(THEME, width="single", ncols=3)
    series, field, grid = fig.axes
    series.plot([0, 1, 2], [1, 3, 2], label="a", **st.line_style(THEME, "simulated"))
    series.set_title("t")
    series.set_ylabel("flow")
    st.style_axes(series, THEME)
    st.legend(series, THEME)
    st.note(series, "NSE 0.8", THEME, loc="lower right")
    image = field.imshow([[0, 1], [2, 3]], cmap="viridis", extent=(0, 4000, 0, 4000))
    st.map_axes(field, THEME)
    st.scale_bar(field, THEME)
    st.colorbar(fig, image, field, THEME, label="$\\mathregular{m^{2}}$", extend="max")
    grid.plot([18000, 18100, 18200], [1, 2, 3], **st.line_style(THEME, "observed"))
    st.style_axes(grid, THEME, dates=True)
    st.panel_labels(fig.axes[:2], THEME)
    return fig


def png(tmp_path, name: str) -> bytes:
    (path,) = st.save(draw(), tmp_path / name, THEME)
    return path.read_bytes()


@pytest.mark.parametrize(("width", "mm"), [("single", 85), ("double", 180), (100, 100)])
def test_width_in_millimetres(width, mm) -> None:
    assert st.new_figure(THEME, width=width).get_figwidth() * 25.4 == pytest.approx(mm)


def test_legend_sits_above_the_axes_with_or_without_a_title() -> None:
    for title in ("", "a title"):
        fig = st.new_figure(THEME)
        ax = fig.axes[0]
        ax.plot([0, 1], [0, 1], label="a")
        ax.set_title(title)
        st.style_axes(ax, THEME)
        leg = st.legend(ax, THEME)
        fig.canvas.draw()
        assert leg.get_window_extent().y0 >= ax.get_window_extent().y1
        assert leg.get_window_extent().y1 <= fig.bbox.y1 + 1


def test_drawing_and_saving_leave_rcparams_unchanged(tmp_path) -> None:
    before = dict(matplotlib.rcParams)
    paths = st.save(draw(), tmp_path / "f.PNG", THEME, formats=("png", "svg", "pdf"))
    assert [p.name for p in paths] == ["f.png", "f.svg", "f.pdf"]
    assert dict(matplotlib.rcParams) == before


def test_the_output_does_not_depend_on_the_rcparams_of_the_caller(tmp_path) -> None:
    plain = png(tmp_path, "plain")
    with matplotlib.rc_context(CALLER_RC):
        assert png(tmp_path, "caller") == plain


def test_two_threads_write_the_same_png(tmp_path) -> None:
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def job(i: int) -> None:
        try:
            fig = draw()
            barrier.wait()
            st.save(fig, tmp_path / f"t{i}", THEME)
        except Exception as exc:  # noqa: BLE001  the test reports every failure
            errors.append(exc)

    threads = [threading.Thread(target=job, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert (tmp_path / "t0.png").read_bytes() == (tmp_path / "t1.png").read_bytes()


def test_save_checks_every_format_before_it_writes(tmp_path) -> None:
    with pytest.raises(ValueError, match="Known formats"):
        st.save(draw(), tmp_path / "f", THEME, formats=("png", "gif"))
    assert not list(tmp_path.iterdir())
