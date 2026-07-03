"""The LAK OUTLETS builder (surverse / spillway).

An outlet row follows the FloPy layout
``[outletno, lakein, lakeout, couttype, invert, width, rough, slope]``. The
tests check:

* WEIR / MANNING / SPECIFIED each build the right row, with MANNING carrying
  ``rough`` / ``slope`` and SPECIFIED carrying no geometry;
* ``lakeout = 0`` (config) maps to ``-1`` (external boundary, FloPy convention)
  and a downstream lake number is translated to its 0-based index;
* the LAK package always sets ``time_conversion`` / ``length_conversion`` to
  1.0 / 1.0 because HMP runs TDIS in seconds (NOT 86400).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_outlets,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_LAKE_CELLS = [5, 6, 9, 10]


def _grid_4x4(nlay: int = 2) -> SolverMesh:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(nlay)])
    return SolverMesh.from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def test_weir_outlet_row_to_external_boundary() -> None:
    lakes = {
        "lac0": {
            "outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 12.0, "lakeout": 0}],
        }
    }
    rows = build_lake_outlets(None, lakes=lakes)
    assert len(rows) == 1
    outletno, lakein, lakeout, couttype, invert, width, rough, slope = rows[0]
    assert outletno == 0
    assert lakein == 0
    assert lakeout == -1  # config 0 -> external boundary (FloPy -1)
    assert couttype == "WEIR"
    assert invert == pytest.approx(87.0)
    assert width == pytest.approx(12.0)
    # WEIR ignores rough / slope.
    assert rough == 0.0
    assert slope == 0.0


def test_manning_outlet_carries_rough_and_slope() -> None:
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "MANNING",
                    "invert": 90.0,
                    "width": 5.0,
                    "rough": 0.03,
                    "slope": 1.0e-3,
                }
            ],
        }
    }
    rows = build_lake_outlets(None, lakes=lakes)
    _, _, lakeout, couttype, invert, width, rough, slope = rows[0]
    assert couttype == "MANNING"
    assert lakeout == -1
    assert invert == pytest.approx(90.0)
    assert width == pytest.approx(5.0)
    assert rough == pytest.approx(0.03)
    assert slope == pytest.approx(1.0e-3)


def test_specified_outlet_has_no_geometry() -> None:
    lakes = {"lac0": {"outlets": [{"couttype": "SPECIFIED", "lakeout": 0}]}}
    rows = build_lake_outlets(None, lakes=lakes)
    _, _, _, couttype, invert, width, rough, slope = rows[0]
    assert couttype == "SPECIFIED"
    assert (invert, width, rough, slope) == (0.0, 0.0, 0.0, 0.0)


def test_specified_outlet_emits_a_period_rate_row() -> None:
    # A SPECIFIED outlet must emit a PERIOD 'rate' row keyed by the global outlet
    # number, else MF6 initialises the rate to zero and the outlet releases nothing.
    from hydromodpy.solver.modflow6.builders.lake import _emit_outlet_rate_rows

    lakes = {
        "lac0": {
            "outlets": [
                {"couttype": "WEIR", "lakeout": 0},  # global outlet 0
                {"couttype": "SPECIFIED", "lakeout": 0, "rate": -2.5},  # global outlet 1
            ]
        }
    }
    period_rows: dict[int, list[list[object]]] = {}
    _emit_outlet_rate_rows(
        None,
        lakes=lakes,
        mode="inline",
        min_periods=64,
        nper=1,
        period_rows=period_rows,
        ts_series=[],
    )
    assert [1, "rate", -2.5] in period_rows[0]


def test_outlet_routes_directly_to_downstream_lake() -> None:
    # Preretenue (lac0) -> retenue (lac1) via a WEIR with lakeout=2 (the second
    # lake, 1-based).
    lakes = {
        "lac0": {"outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 30.0, "lakeout": 2}]},
        "lac1": {"outlets": []},
    }
    rows = build_lake_outlets(None, lakes=lakes)
    assert len(rows) == 1
    _, lakein, lakeout, *_ = rows[0]
    assert lakein == 0  # from lac0
    assert lakeout == 1  # config lakeout=2 -> 0-based index 1, NOT external (-1)


def test_lakeout_two_on_two_lake_model_resolves_to_index_one() -> None:
    # Config lakeout is 1-based: lakeout=2 is the second lake, which FloPy stores
    # as 0-based index 1 (written to the MF6 file as lake number 2).
    lakes = {
        "lac0": {"outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 30.0, "lakeout": 2}]},
        "lac1": {"outlets": []},
    }
    rows = build_lake_outlets(None, lakes=lakes)
    _, _, lakeout, *_ = rows[0]
    assert lakeout == 1


def test_lakeout_greater_than_lake_count_is_rejected() -> None:
    # lakeout=2 but only one lake declared: no downstream lake to route to.
    lakes = {
        "lac0": {"outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 30.0, "lakeout": 2}]},
    }
    with pytest.raises(ValueError, match="no matching downstream lake"):
        build_lake_outlets(None, lakes=lakes)


def test_outlet_routing_a_lake_to_itself_is_rejected() -> None:
    # lac0 is the first lake; lakeout=1 would route it back to itself.
    lakes = {
        "lac0": {"outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 30.0, "lakeout": 1}]},
        "lac1": {"outlets": []},
    }
    with pytest.raises(ValueError, match="routes the lake to itself"):
        build_lake_outlets(None, lakes=lakes)


def test_manning_outlet_rejects_zero_slope() -> None:
    lakes = {
        "lac0": {
            "outlets": [{"couttype": "MANNING", "invert": 90.0, "width": 5.0, "rough": 0.03}],
        }
    }
    with pytest.raises(ValueError, match="positive slope"):
        build_lake_outlets(None, lakes=lakes)


def test_weir_outlet_requires_invert() -> None:
    lakes = {"lac0": {"outlets": [{"couttype": "WEIR", "width": 5.0}]}}
    with pytest.raises(ValueError, match="requires an invert"):
        build_lake_outlets(None, lakes=lakes)


def test_unknown_couttype_is_rejected() -> None:
    lakes = {"lac0": {"outlets": [{"couttype": "SIPHON", "invert": 1.0, "width": 1.0}]}}
    with pytest.raises(ValueError, match="couttype must be one of"):
        build_lake_outlets(None, lakes=lakes)


def _model_with_outlet() -> SimpleNamespace:
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    abacus = [(50.0, 0.0, 4.0), (100.0, 200.0, 4.0)]
    return SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": polygon,
                        "bedleak": 0.3,
                        "abacus": abacus,
                        "stageinit": 80.0,
                        "outlets": [
                            {"couttype": "WEIR", "invert": 95.0, "width": 8.0, "lakeout": 0}
                        ],
                        "rainfall": {"value": 4.0, "units": "mm/day"},
                    }
                }
            },
        ),
    )


def test_lak_package_args_attach_outlets_and_seconds_conversions() -> None:
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake={"lac0": _LAKE_CELLS})
    args = build_lak_package_args(
        _model_with_outlet(),
        solver_mesh=masked,
        lake_cell_ids_by_lake={"lac0": _LAKE_CELLS},
    )
    assert args is not None
    assert args["noutlets"] == 1
    assert args["outlets"][0][3] == "WEIR"
    # rainfall (rate L/T) lands in perioddata as m/s.
    period_rows = args["perioddata"][0]
    rainfall = [r for r in period_rows if r[1] == "rainfall"]
    assert rainfall and rainfall[0][2] == pytest.approx(4.0e-3 / 86400.0)
    # HMP TDIS is seconds -> conversions stay 1.0, NOT 86400 (negative assertion).
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0
    assert args["time_conversion"] != 86400.0


def test_lak_package_args_omit_outlets_when_none() -> None:
    polygon = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    model = SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": polygon,
                        "bedleak": 0.3,
                        "abacus": [(50.0, 0.0, 4.0), (100.0, 200.0, 4.0)],
                    }
                }
            },
        ),
    )
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake={"lac0": _LAKE_CELLS})
    args = build_lak_package_args(
        model, solver_mesh=masked, lake_cell_ids_by_lake={"lac0": _LAKE_CELLS}
    )
    assert args is not None
    assert args["noutlets"] == 0
    # No empty recarrays handed to FloPy.
    assert "outlets" not in args
    assert "perioddata" not in args
