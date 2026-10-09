"""The Validation page draws the solvers of a case on one figure.

The runs of one case that share the points and the reference go on the same
figure, each with the colour and the shape of its solver, and a second panel
draws each run minus the reference.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def V():
    """hmp_validation is a module of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    import hmp_validation

    yield hmp_validation
    sys.path.remove(str(EXT))


def _record(solver: str, simulated: list[float], reference=(10.0, 9.0, 8.0), log=False):
    series = {
        "name": "Head profile",
        "x": [0.0, 50.0, 100.0],
        "reference": list(reference),
        "simulated": simulated,
        "x_label": "x (m)",
        "y_label": "head (m)",
        "log": log,
    }
    return {"solver": solver, "params": solver, "series": [series]}


def test_the_solvers_of_a_case_share_one_figure(V) -> None:
    html = V.figures_html(
        [
            _record("modflow6", [10.0, 9.01, 8.0]),
            _record("modflow_nwt", [10.0, 8.99, 8.0]),
            _record("modflow6_irregular_tri", [10.0, 9.02, 8.0]),
        ]
    )
    assert html.count("<figure") == 1
    for label in ("NWT", "MF6", "MF6 triangles", "reference"):
        assert f">{label}</span>" in html
    assert "minus the reference" in html


def test_a_solver_keeps_its_colour_whatever_the_order(V) -> None:
    html = V.figures_html([_record("modflow6", [10, 9, 8]), _record("modflow_nwt", [10, 9, 8])])
    nwt = V.SOLVER_ORDER.index("modflow_nwt")
    mf6 = V.SOLVER_ORDER.index("modflow6")
    assert f'hmp-val-mk hmp-val-s{nwt}" viewBox' in html
    assert html.index(f"hmp-val-s{nwt}") < html.index(f"hmp-val-s{mf6}")


def test_runs_with_another_reference_get_their_own_figure(V) -> None:
    html = V.figures_html(
        [_record("modflow6", [10, 9, 8]), _record("modflow6_scaled_up", [20, 18, 16], (20, 18, 16))]
    )
    assert html.count("<figure") == 2


def test_a_reference_moved_by_the_discretisation_still_shares_the_figure(V) -> None:
    html = V.figures_html(
        [_record("modflow6", [10, 9, 8]), _record("modflow_nwt", [10, 9, 8], (10.0, 9.02, 8.0))]
    )
    assert html.count("<figure") == 1
    assert "reference of each run" in html
    assert html.count('class="hmp-val-ref-own') == 2


def test_a_log_scale_figure_has_no_difference_panel(V) -> None:
    html = V.figures_html([_record("modflow6", [1.0, 0.1, 0.01], (1.0, 0.1, 0.01), log=True)])
    assert html.count("<figure") == 1
    assert "minus the reference" not in html
    assert "log scales" in html


def test_two_runs_of_one_solver_are_told_apart(V) -> None:
    first = _record("modflow6", [10, 9, 8])
    second = _record("modflow6", [10, 9.1, 8])
    second["params"] = "modflow6_k_only"
    html = V.figures_html([first, second])
    assert html.count("<figure") == 1
    assert len(set(V.re.findall(r'hmp-val-mk hmp-val-s(\d)" viewBox', html))) == 2


def test_no_curve_draws_nothing(V) -> None:
    assert V.figures_html([{"solver": "modflow6", "series": []}]) == ""
