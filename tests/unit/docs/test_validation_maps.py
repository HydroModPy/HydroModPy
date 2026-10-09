"""Maps, space-time errors and calibration landscapes of the Validation page."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.validation.helpers import results

EXT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def F():
    sys.path.insert(0, str(EXT))
    import hmp_validation_figures

    yield hmp_validation_figures
    sys.path.remove(str(EXT))


def _squares(n: int = 4) -> list[np.ndarray]:
    return [
        np.array([[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]], dtype=float)
        for j in range(n)
        for i in range(n)
    ]


def _record_with(func, *args, **kwargs) -> dict:
    record = results.new_record()
    with results.recording(record):
        func(*args, **kwargs)
    return record


def _triangles(n: int = 4) -> list[np.ndarray]:
    out = []
    for j in range(n):
        for i in range(n):
            out.append(np.array([[i, j], [i + 1, j], [i, j + 1]], dtype=float))
            out.append(np.array([[i + 1, j], [i + 1, j + 1], [i, j + 1]], dtype=float))
    return out


def test_record_map_keeps_the_error_on_shared_vertices():
    sim = np.linspace(1.0, 2.0, 32)
    sim[3] = np.nan
    ref = np.full(32, 1.5)
    rec = _record_with(
        results.record_map,
        "map",
        _triangles(),
        sim,
        ref,
        overlay={"well": [2.0, 2.0], "ignored": 1},
    )
    (m,) = rec["maps"]
    assert len(m["vertices"]) == 25
    assert len(m["faces"]) == 32
    assert m["error"][3] is None
    assert m["error"][0] == -0.5
    assert m["overlay"] == {"well": [2.0, 2.0]}


def test_record_map_turns_rectangles_into_a_grid():
    sim = np.arange(16.0)
    rec = _record_with(results.record_map, "map", _squares()[::-1], sim, np.zeros(16))
    (m,) = rec["maps"]
    assert "vertices" not in m
    assert m["grid"] == {"x_edges": [0, 1, 2, 3, 4], "y_edges": [0, 1, 2, 3, 4]}
    # The squares came in reverse order: the grid puts each value back on its cell.
    assert m["error"] == list(np.arange(16.0)[::-1])


def test_record_map_regular_grid_form():
    rec = _record_with(
        results.record_map,
        "map",
        {"x_edges": [0, 1, 2, 3], "y_edges": [0, 1, 2]},
        np.zeros(6),
        np.ones(6),
    )
    (m,) = rec["maps"]
    assert m["grid"]["x_edges"] == [0, 1, 2, 3]
    assert m["error"] == [-1.0] * 6


def test_record_map_ignores_a_size_mismatch():
    rec = _record_with(results.record_map, "map", _squares(), np.zeros(3), np.zeros(3))
    assert rec["maps"] == []


def test_record_spacetime_thins_the_grid_and_keeps_the_error():
    x = np.linspace(0, 100, 301)
    t = np.linspace(1, 50, 200)
    ref = np.zeros((200, 301))
    sim = np.full((200, 301), 0.123456789)
    rec = _record_with(
        results.record_spacetime, "e", x, t, ref, sim, x_label="x (m)", t_label="t (d)", unit="m"
    )
    (s,) = rec["spacetime"]
    assert len(s["x"]) == results.MAX_SPACETIME_X and len(s["t"]) == results.MAX_SPACETIME_T
    assert len(s["error"]) == results.MAX_SPACETIME_T
    assert len(s["error"][0]) == results.MAX_SPACETIME_X
    assert s["error"][0][0] == 0.123


def test_record_comparison_keeps_the_spacetime_field():
    comparison = SimpleNamespace(
        metadata={"case_id": "c"},
        x=np.linspace(0, 10, 5),
        elapsed_days=np.array([1.0, 2.0, 3.0]),
        analytical_profiles=np.zeros((3, 5)),
        numerical_profiles=np.ones((3, 5)),
    )
    rec = _record_with(results.record_comparison, comparison)
    assert rec["series"] and rec["spacetime"][0]["error"][2][4] == 1.0


def test_record_comparison_keeps_the_map():
    comparison = SimpleNamespace(
        metadata={"case_id": "c"},
        map_cell_polygons=_squares(2),
        map_simulated=np.ones(4),
        map_reference=np.zeros(4),
        map_overlay={"coast_circle": [1.0, 1.0, 0.8]},
    )
    rec = _record_with(results.record_comparison, comparison)
    assert rec["maps"][0]["overlay"]["coast_circle"] == [1.0, 1.0, 0.8]


def _map_panel(shift: float) -> dict:
    rec = _record_with(
        results.record_map,
        "map",
        _squares(),
        np.arange(16.0) * 0.1 + shift,
        np.arange(16.0) * 0.1,
        overlay={"coast_circle": [2.0, 2.0, 1.5], "well": [2.0, 2.0]},
    )
    m = rec["maps"][0]
    m["error"][0] = None
    return m


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_draw_maps(F, theme):
    data = F.draw_maps([("MF6", _map_panel(0.1)), ("NWT", _map_panel(-0.2))], theme)
    assert _is_webp(data) and len(data) < F.MAX_BYTES


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_draw_spacetime(F, theme):
    x = np.linspace(0, 10, 12)
    t = np.linspace(1, 5, 9)
    rec = _record_with(
        results.record_spacetime,
        "e",
        x,
        t,
        np.zeros((9, 12)),
        np.outer(np.sin(t), np.cos(x)),
        x_label="x (m)",
        t_label="time (d)",
        unit="m",
    )
    s = rec["spacetime"][0]
    data = F.draw_spacetime([("MF6", s), ("NWT", s)], theme)
    assert _is_webp(data) and len(data) < F.MAX_BYTES


def _samples(names: list[str], log: bool = True) -> list[dict]:
    rng = np.random.default_rng(1)
    out = []
    for method in ("CMA-ES", "TPE"):
        pts = (
            10 ** rng.uniform(-6, -3, (30, len(names)))
            if log
            else rng.uniform(1, 2, (30, len(names)))
        )
        obj = ((np.log10(pts) + 4.5) ** 2).sum(axis=1) + 1e-3
        rec = _record_with(
            results.record_samples, method, names, pts, obj, {n: 10**-4.5 for n in names}
        )
        out.append(rec["samples"][0])
    return out


@pytest.mark.parametrize("names", [["k"], ["k", "s"], ["k", "s", "r"]])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_draw_samples(F, names, theme):
    data = F.draw_samples(_samples(names), theme)
    assert _is_webp(data) and len(data) < F.MAX_BYTES


def test_figures_html_writes_once_and_names_both_themes(F, tmp_path):
    F.set_output(tmp_path)
    records = [
        {"solver": "modflow6", "case": "a", "maps": [_map_panel(0.1)]},
        {"solver": "modflow_nwt", "case": "a", "maps": [_map_panel(0.2)]},
        {"solver": "modflow6", "samples": _samples(["k", "s"]), "params": "x"},
        {"solver": "modflow6", "series": []},
    ]

    def call():
        return F.figures_html(
            records,
            label=lambda r: r["solver"],
            order=lambda r: r["solver"],
            docname="theory/validation",
        )

    html = call()
    files = sorted((tmp_path / F.SUBDIR).iterdir())
    assert len(files) == 4
    assert html.count('class="only-light"') == 2 and html.count('class="only-dark"') == 2
    assert 'src="../_static/validation-figures/' in html
    mtimes = [f.stat().st_mtime_ns for f in files]
    assert call() == html
    assert [f.stat().st_mtime_ns for f in files] == mtimes


def test_a_record_without_data_draws_nothing(F, tmp_path):
    F.set_output(tmp_path)
    html = F.figures_html(
        [{"solver": "modflow6", "series": []}],
        label=lambda r: "x",
        order=lambda r: "x",
        docname="validation",
    )
    assert html == ""
    assert not (tmp_path / F.SUBDIR).exists()
