from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import LineString

import hydromodpy.solver.modflow6.builders.sfr as sfr_module
from hydromodpy.solver.modflow6.builders import (
    build_lake_mover_records,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow6.builders._sfr_network import crossing_pieces
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord
from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    SfrReachRecord,
    build_sfr_package_args,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

# Without river chains, a reach is shared among the cells it crosses, as GridIntersect shared it.
#
# The SFR builder split a reach line with ``flopy.utils.GridIntersect`` on a
# ``VertexGrid`` rebuilt from the mesh, dropped the pieces under 1e-6 m and
# ordered the cells by the projection of each piece's midpoint. On a mesh that
# carries no ``rivers`` chain it now cuts the line at the cell boundaries of the
# cell mesh. The two are compared on a regular grid at a non-integer origin, on
# the triangles and on the Voronoi dual of a committed bundle: same cells in the
# same order, lengths within 1e-9 m.

_LENGTH_ATOL_M = 1e-9


_BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"


_UNIT_LINES = (
    LineString([(0.05, 0.93), (0.31, 0.62), (0.47, 0.55), (0.66, 0.31), (0.97, 0.08)]),
    LineString([(0.12, 0.1), (0.4, 0.42), (0.41, 0.8), (0.9, 0.86)]),
)


def _regular() -> PlanarCellMesh:
    mesh = solver_mesh_from_structured_arrays(
        nrow=30,
        ncol=40,
        top=np.zeros((30, 40)),
        botm=np.full((1, 30, 40), -10.0),
        dx=37.3,
        dy=41.7,
        xoff=350_000.37,
        yoff=6_780_000.11,
    )
    return mesh.cell_mesh


def _meshes() -> dict[str, PlanarCellMesh]:
    return {
        "regular": _regular(),
        "triangles": bundle_triangles(_BUNDLE),
        "dual": bundle_dual(_BUNDLE),
    }


def _lines_on(cell_mesh: PlanarCellMesh) -> list[LineString]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(line, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for line in _UNIT_LINES
    ]


def _gridintersect_reach(cell_mesh: PlanarCellMesh, line: LineString) -> list[tuple[int, float]]:
    """The split of the former builder: GridIntersect pieces ordered along the line."""
    n_cells = cell_mesh.n_cells
    disv = to_flopy_disv_args(cell_mesh.mesh, top=np.zeros(n_cells), botm=np.full((1, n_cells), -1))
    grid = VertexGrid(
        vertices=disv["vertices"],
        cell2d=disv["cell2d"],
        top=np.zeros(n_cells),
        botm=np.full((1, n_cells), -1.0),
        nlay=1,
        ncpl=n_cells,
        xoff=0.0,
        yoff=0.0,
    )
    pieces = []
    for row in GridIntersect(grid).intersect(line, geo_dataframe=False):
        length = float(row["lengths"])
        if length < 1e-6:
            continue
        middle = row["ixshapes"].interpolate(0.5, normalized=True)
        pieces.append((float(line.project(middle)), int(row["cellids"]), length))
    pieces.sort()
    return [(cell, length) for _, cell, length in pieces]


@pytest.mark.parametrize("name", ["regular", "triangles", "dual"])
def test_the_reach_pieces_are_those_of_gridintersect(name: str) -> None:
    cell_mesh = _meshes()[name]
    for line in _lines_on(cell_mesh):
        expected = _gridintersect_reach(cell_mesh, line)
        pieces = crossing_pieces(cell_mesh, line)
        assert [piece.cell for piece in pieces] == [cell for cell, _ in expected]
        np.testing.assert_allclose(
            [piece.length for piece in pieces],
            [length for _, length in expected],
            rtol=0.0,
            atol=_LENGTH_ATOL_M,
        )
        assert sum(piece.length for piece in pieces) == pytest.approx(line.length, rel=1e-12)


# SFR <-> LAK coupling through MVR records (both directions, 2-package block).


def test_lake_outlet_mover_reach_targets_sfr() -> None:
    # The spillway-release direction: a LAK outlet mover carrying `reach` becomes
    # a LAK -> SFR record (receiver id = 1-based reach - 1).
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "kind": "WEIR",
                    "invert": 95.0,
                    "width": 5.0,
                    "lakeout": 0,
                    "mover": {"reach": 3, "mvrtype": "FACTOR", "value": 1.0},
                }
            ]
        }
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert records == [["LAK", 0, "SFR", 2, "FACTOR", 1.0]]


def test_outlet_numbering_stays_in_lockstep_with_mover_less_outlets() -> None:
    # A direct outlet without a mover still advances the shared outlet counter,
    # so the mover on the SECOND outlet provides from outletno 1.
    lakes = {
        "lac0": {
            "outlets": [
                {"kind": "WEIR", "invert": 95.0, "width": 5.0, "lakeout": 0},
                {
                    "kind": "SPECIFIED",
                    "lakeout": 0,
                    "mover": {"reach": 1, "mvrtype": "UPTO", "value": 0.5},
                },
            ]
        }
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert records == [["LAK", 1, "SFR", 0, "UPTO", 0.5]]


def test_lake_outlet_mover_reach_zero_raises() -> None:
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "kind": "WEIR",
                    "invert": 95.0,
                    "width": 5.0,
                    "lakeout": 0,
                    "mover": {"reach": 0},
                }
            ]
        }
    }
    with pytest.raises(ValueError, match="reach"):
        build_lake_mover_records(None, lakes=lakes)


def test_mixed_lak_sfr_records_make_a_two_package_block() -> None:
    # SFR -> LAK (the Cheze feed) merged with LAK -> SFR (spillway): the MVR block
    # references two distinct packages and the packages list is derived from the
    # record rows, exactly as build.py assembles it.
    rows = build_mvr_period_records(
        [
            MoverRecord(provider="SFR", provider_id=7, receiver="LAK", receiver_id=0),
            MoverRecord(
                provider="LAK",
                provider_id=0,
                receiver="SFR",
                receiver_id=8,
                mvrtype="UPTO",
                value=0.1,
            ),
        ]
    )
    assert mover_package_count(rows) == 2
    packages = sorted({(str(row[0]),) for row in rows} | {(str(row[2]),) for row in rows})
    assert packages == [("LAK",), ("SFR",)]


# SFR is lake-independent by construction: no import edge to the LAK builder.


def test_sfr_builder_never_imports_the_lake_builder() -> None:
    tree = ast.parse(Path(sfr_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("builders.lake" in name for name in imported), (
        "builders/sfr.py must stay standalone: the SFR-LAK coupling is MVR data, "
        "never an import edge to builders/lake.py."
    )


# The SFR Picard shortcut must not survive a mover feeding the reaches.


def _args(**definition):
    import inspect

    signature = inspect.signature(build_sfr_package_args)
    return signature, definition


def test_the_builder_reads_route_drainage_before_capping_picard():
    # The guard lives in the source, not behind a full model build: assert the
    # condition itself, so a refactor that drops `route_drainage` fails here.
    import inspect

    source = inspect.getsource(build_sfr_package_args)
    assert 'args["maximum_picard_iterations"] = 1' in source
    line = next(
        line for line in source.splitlines() if "downstream_increasing" in line and "if " in line
    )
    assert "route_drainage" in line, (
        "The one-Picard-pass shortcut assumes nothing moves water INTO the reaches. "
        "With route_drainage the DRN->SFR mover inflow updates once per outer "
        "iteration and the solution creeps instead of converging."
    )


# The streambed-top floor must not re-break the monotone-downhill order.
#
# The per-cell cell-bottom floor lifts a reach's streambed top so its bed stays
# inside the aquifer cell. A lake-enforced routing DEM can hand a DOWNSTREAM reach
# a much higher cell bottom than its upstream neighbor, so flooring it up would
# push it above the upstream reach and re-break the monotone order the single-Picard
# routing (``maximum_picard_iterations=1``) relies on. ``build_sfr_package_args``
# floors every reach first, then re-sweeps outlet->head lifting upstream reaches so
# both the floor and monotonicity hold.

# Defaults the builder applies when the definition omits them.
_RBTH = 1.0  # streambed_thickness default


_RTP_ABOVE_BOTTOM_M = 0.1  # bed keep-out above the cell bottom


_MIN_SLOPE = 1e-4  # min_slope default


def _fake_model():
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={}),
        nper=1,
        perlen=np.asarray([86400.0], dtype=float),
        steady=(False,),
        time_grid=None,
        time_units="seconds",
        model_output_name="rtptest",
    )


def _two_cell_mesh(*, up_bottom: float, down_bottom: float) -> SolverMesh:
    # One row of two cells: cell2d 0 (upstream), cell2d 1 (downstream). The
    # downstream cell gets a HIGH bottom so its floor lifts rtp above the upstream.
    top = np.full((1, 2), 100.0)
    botm = np.array([[[up_bottom, down_bottom]]], dtype=float)  # (nlay=1, nrow=1, ncol=2)
    return solver_mesh_from_structured_arrays(nrow=1, ncol=2, top=top, botm=botm, dx=10.0, dy=10.0)


def _chain_network(*, rtp_up: float, rtp_down: float) -> ResolvedSfrNetwork:
    up = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_up,
        upstream=(),
        downstream=(1,),
        is_headwater=True,
    )
    down = SfrReachRecord(
        ifno=1,
        cellid=(0, 1),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_down,
        upstream=(0,),
        downstream=(),
    )
    return ResolvedSfrNetwork(network_id="net0", reaches=(up, down), definition={})


def _rtp_by_ifno(packagedata: list[list]) -> dict[int, float]:
    # PACKAGEDATA row layout: [ifno, cellid, rlen, rwid, rgrd, rtp, rbth, ...].
    return {int(row[0]): float(row[5]) for row in packagedata}


def test_floor_lifting_a_downstream_reach_restores_monotone_order() -> None:
    # Start monotone (up 60.0 > down 59.9). The downstream cell bottom (65.0)
    # floors rtp[down] up to 66.1, above the upstream reach: without the re-sweep
    # the package would ship an uphill step. The fix lifts the upstream reach back
    # above its floored downstream neighbor.
    mesh = _two_cell_mesh(up_bottom=40.0, down_bottom=65.0)
    network = _chain_network(rtp_up=60.0, rtp_down=59.9)
    args = build_sfr_package_args(_fake_model(), networks={"net0": network}, solver_mesh=mesh)

    # This network is downstream-increasing, so the single-Picard fast path is on:
    # that is exactly the routing the monotone order must hold for.
    assert args["maximum_picard_iterations"] == 1

    rtp = _rtp_by_ifno(args["packagedata"])
    floor_down = 65.0 + _RBTH + _RTP_ABOVE_BOTTOM_M
    # The downstream reach kept its floor (its bed stays inside the aquifer cell).
    assert rtp[1] == pytest.approx(floor_down)
    # The upstream reach was lifted above the floored downstream one: order restored.
    assert rtp[0] > rtp[1]
    drop = _MIN_SLOPE * 0.5 * (10.0 + 10.0)
    assert rtp[0] == pytest.approx(floor_down + drop)
    # Both beds still sit above their own cell bottom (the floor held).
    assert rtp[0] - _RBTH >= 40.0
    assert rtp[1] - _RBTH >= 65.0


def test_floor_that_does_not_break_order_leaves_the_upstream_reach_untouched() -> None:
    # When the floor does not fire (both cells sit far below the streambed), the
    # re-sweep is a no-op: the reaches keep their declared tops.
    mesh = _two_cell_mesh(up_bottom=40.0, down_bottom=40.0)
    network = _chain_network(rtp_up=60.0, rtp_down=59.9)
    args = build_sfr_package_args(_fake_model(), networks={"net0": network}, solver_mesh=mesh)

    rtp = _rtp_by_ifno(args["packagedata"])
    assert rtp[0] == pytest.approx(60.0)
    assert rtp[1] == pytest.approx(59.9)
    assert rtp[0] > rtp[1]
