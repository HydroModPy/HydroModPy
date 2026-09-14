"""Multi-lake build with a concrete weir between preretenue and retenue.

Two lakes share one LAK package (``nlakes = 2``): lac0 = preretenue (upstream),
lac1 = retenue (downstream). The concrete sill between them is a WEIR OUTLET of
the preretenue whose ``invert`` is the crest elevation and whose ``lakeout`` is
the downstream lake (direct LAK -> LAK routing, no MVR). The tests check:

* ``packagedata`` has one row per lake (two rows), each with its own boundname
  and strt; ``ntables`` == 2 with one ``laktab`` per lake;
* ``connectiondata`` covers both lakes (``ifno`` 0 and 1 both present);
* the concrete-weir outlet row has ``invert`` == crest and routes to the
  downstream lake (``lakeout`` != external -1);
* the crossed-weir sill (0 -> 1 and 1 -> 0 at the same invert) emits two outlets
  to approximate a shared surface above the crest. Both legs route DIRECTLY
  (lac1 -> lac0 with ``lakeout = 1`` is a valid direct destination; verified to
  build and run in MF6). A mover on the reverse leg is an optional CONTROLLED
  alternative (FACTOR / UPTO / EXCESS / THRESHOLD), not a requirement.

A separate guard rejects two lakes that resolve to the same grid cell (MF6 LAK
allows one lake per cell).
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
    resolve_lake_cells_for_active_lakes,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

# A concrete sill crest elevation shared by the preretenue spill and the crossed
# weirs.
_CREST = 87.0


def _grid_4x4(nlay: int = 2) -> SolverMesh:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(nlay)])
    return SolverMesh.from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def _two_lake_model(*, lac0_outlets: list[dict], lac1_outlets: list[dict]) -> SimpleNamespace:
    # lac0 in the lower-left quad, lac1 in the upper-right quad of the 4x4 grid.
    poly0 = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    poly1 = Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)])
    abacus0 = [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)]
    abacus1 = [(50.0, 0.0, 9.0), (90.0, 360.0, 9.0)]
    return SimpleNamespace(
        model_output_name="preretenue_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["reservoir"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": poly0,
                        "bedleak": 0.2,
                        "abacus": abacus0,
                        "stageinit": 60.0,
                        "outlets": lac0_outlets,
                    },
                    "lac1": {
                        "polygon": poly1,
                        "bedleak": 0.2,
                        "abacus": abacus1,
                        "stageinit": 70.0,
                        "outlets": lac1_outlets,
                    },
                }
            },
        ),
    )


def test_two_lake_build_has_two_lakes_and_two_tables() -> None:
    model = _two_lake_model(
        lac0_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 30.0, "lakeout": 2}],
        lac1_outlets=[],
    )
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None

    # Two lakes -> two packagedata rows, two laktab tables, distinct boundnames.
    assert args["nlakes"] == 2
    assert len(args["packagedata"]) == 2
    assert args["ntables"] == 2
    assert len(args["laktab_specs"]) == 2
    boundnames = {row[3] for row in args["packagedata"]}
    assert boundnames == {"lac0", "lac1"}

    # connectiondata covers both lakes: ifno (column 0) holds 0 and 1.
    ifnos = {row[0] for row in args["connectiondata"]}
    assert ifnos == {0, 1}

    # Each lake's strt comes from its own abacus floor / stageinit.
    strt_by_name = {row[3]: row[1] for row in args["packagedata"]}
    assert strt_by_name["lac0"] == pytest.approx(60.0)
    assert strt_by_name["lac1"] == pytest.approx(70.0)


def test_concrete_weir_routes_preretenue_to_retenue_at_crest() -> None:
    model = _two_lake_model(
        lac0_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 30.0, "lakeout": 2}],
        lac1_outlets=[],
    )
    rows = build_lake_outlets(model, lakes=model.flow.sinks_sources["lakes"])
    assert len(rows) == 1
    outletno, lakein, lakeout, couttype, invert, width, rough, slope = rows[0]
    assert lakein == 0  # spills from lac0 (preretenue)
    assert lakeout == 1  # routed straight to the downstream lake, NOT external (-1)
    assert lakeout != -1
    assert couttype == "WEIR"
    assert invert == pytest.approx(_CREST)  # invert == concrete crest elevation
    assert width == pytest.approx(30.0)


def test_crossed_weirs_route_directly_both_ways() -> None:
    # Partially submerged sill, the recommended plain form: lac0 -> lac1
    # (lakeout = 2) and lac1 -> lac0 (lakeout = 1) are BOTH direct LAK -> LAK
    # outlets at the same invert, no MVR. lakeout = 1 is a valid destination (the
    # first lake, 0-based index 0); only lakeout = 0 (external) and a self-route
    # are rejected. MF6 accepts this 2-cycle of direct outlets (verified).
    model = _two_lake_model(
        lac0_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 100.0, "lakeout": 2}],
        lac1_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 100.0, "lakeout": 1}],
    )
    rows = build_lake_outlets(model, lakes=model.flow.sinks_sources["lakes"])
    assert len(rows) == 2
    assert all(row[4] == pytest.approx(_CREST) for row in rows)
    # One spills from lac0, the other from lac1; each routes to the other lake
    # (0-based lakeouts {1, 0}), never external (-1).
    assert sorted(row[1] for row in rows) == [0, 1]
    assert sorted(row[2] for row in rows) == [0, 1]
    assert all(row[2] != -1 for row in rows)

    # Direct routing carries no mover: the LAK package stays MVR-free.
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    assert "mover_records" not in args
    assert "mover" not in args


def test_crossed_weirs_emit_two_outlets_at_same_invert() -> None:
    # The controlled alternative: lac0 -> lac1 direct, and lac1 -> lac0 routed
    # through MVR (lakeout = 0 + mover.lake = 1) when a FACTOR / UPTO / EXCESS /
    # THRESHOLD rule is wanted on the reverse leg instead of a plain spill.
    model = _two_lake_model(
        lac0_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 100.0, "lakeout": 2}],
        lac1_outlets=[
            {
                "couttype": "WEIR",
                "invert": _CREST,
                "width": 100.0,
                "lakeout": 0,
                "mover": {"lake": 1, "mvrtype": "FACTOR", "value": 1.0},
            }
        ],
    )
    rows = build_lake_outlets(model, lakes=model.flow.sinks_sources["lakes"])
    assert len(rows) == 2  # bidirectional option emits two outlets
    # Both outlets sit at the same crest invert.
    assert all(row[4] == pytest.approx(_CREST) for row in rows)
    # One spills from lac0, the other from lac1 (the two lakein values differ).
    lakeins = sorted(row[1] for row in rows)
    assert lakeins == [0, 1]


def test_crossed_weir_back_route_uses_mover_to_first_lake() -> None:
    # The reverse weir (1 -> 0) MAY be routed via MVR back to lac0 (mover.lake=1,
    # 1-based) when a controlled transfer rule is wanted. This is optional: the
    # direct lakeout = 1 form (test_crossed_weirs_route_directly_both_ways) is the
    # plain spill. Here we assert the MVR record the mover produces.
    model = _two_lake_model(
        lac0_outlets=[{"couttype": "WEIR", "invert": _CREST, "width": 100.0, "lakeout": 2}],
        lac1_outlets=[
            {
                "couttype": "WEIR",
                "invert": _CREST,
                "width": 100.0,
                "lakeout": 0,
                "mover": {"lake": 1, "mvrtype": "FACTOR", "value": 1.0},
            }
        ],
    )
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    assert args["mover"] is True
    # lac1's outlet is outlet number 1 (lac0's outlet is 0); it moves to lac0
    # (receiver index 0).
    assert args["mover_records"] == [["LAK", 1, "LAK", 0, "FACTOR", 1.0]]


def test_two_lake_build_without_outlets_still_builds_both_lakes() -> None:
    # No spill at all: both lakes still appear, just with noutlets == 0.
    model = _two_lake_model(lac0_outlets=[], lac1_outlets=[])
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    assert args["nlakes"] == 2
    assert args["noutlets"] == 0
    assert "outlets" not in args
    assert "mover" not in args


def test_two_overlapping_lakes_are_resolved_cell_disjoint() -> None:
    # Two lake polygons that clip shared grid cells are reconciled, not rejected:
    # MF6 LAK allows one lake per cell, so each shared cell goes to its larger-overlap
    # lake and the footprints come out cell-disjoint. poly_a covers the lower-left 2x2
    # block, poly_b is shifted by one cell so they collide on the coarse 4x4 grid.
    poly_a = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    poly_b = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    model = SimpleNamespace(
        model_output_name="overlap_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["reservoir"],
            sinks_sources={
                "lakes": {
                    "lac0": {"polygon": poly_a, "bedleak": 0.2, "outlets": []},
                    "lac1": {"polygon": poly_b, "bedleak": 0.2, "outlets": []},
                }
            },
        ),
    )
    cells = resolve_lake_cells_for_active_lakes(model, _grid_4x4())
    assert set(cells["lac0"]).isdisjoint(cells["lac1"])
    assert cells["lac0"] and cells["lac1"]  # neither lake was emptied
