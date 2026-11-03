"""A lake fed only by the hillslope drainage still announces MOVER.

``route_drainage`` hands each drain cell to the first reach or lake it meets on
the descent. When the only mover entering a lake comes from DRN, LAK must
advertise MOVER all the same, or MODFLOW 6 stops at the first DRN-to-LAK record.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_drainage_mover_records,
    build_lak_package_args,
    build_mvr_period_records,
)
from hydromodpy.solver.modflow6.builders.sfr import mover_rows_reach_lake
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def _one_lake_model() -> SimpleNamespace:
    polygon = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    return SimpleNamespace(
        model_output_name="drn_to_lake",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": polygon,
                        "bedleak": 0.2,
                        "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                        "initial_stage": 60.0,
                        "outlets": [],
                    }
                }
            },
        ),
    )


def _lake_args(*, external_mover_to_lake: bool) -> dict:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 50.0), np.full((4, 4), 0.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    cells = {"lac0": [0, 1]}
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(
        _one_lake_model(),
        solver_mesh=masked,
        lake_cell_ids_by_lake=cells,
        external_mover_to_lake=external_mover_to_lake,
    )
    assert args is not None
    return args


def _drain_chain_ending_in_a_lake() -> list[list[object]]:
    """MVR rows of a hillslope chain 0 -> 1 -> 2 whose cell 2 is lake number 0."""
    from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork

    receiver = np.array([1, 2, -1])
    faces: list[set[int]] = [{1}, {0, 2}, {1}]
    records = build_drainage_mover_records(
        {"net0": ResolvedSfrNetwork("net0", (), {"route_drainage": True})},
        drn_spd={0: [[0, 0, 100.0, 0.05], [0, 1, 100.0, 0.05]]},
        receiver=receiver,
        basin_cell_mask=np.ones(3, dtype=bool),
        face_adjacency=faces,
        mesh_top=np.zeros(3),
        lake_cells_by_number={0: [2]},
    )
    return build_mvr_period_records(records)


def test_a_drn_row_with_a_lake_receiver_is_counted() -> None:
    rows = _drain_chain_ending_in_a_lake()

    assert [row[2] for row in rows] == ["LAK", "LAK"]
    assert mover_rows_reach_lake(rows) is True


def test_a_drn_row_with_a_reach_receiver_is_not() -> None:
    assert mover_rows_reach_lake([["DRN", 0, "SFR", 3, "FACTOR", 1.0]]) is False
    assert mover_rows_reach_lake([]) is False


def test_lak_announces_mover_when_only_the_drainage_feeds_it() -> None:
    fed = mover_rows_reach_lake(_drain_chain_ending_in_a_lake())

    assert _lake_args(external_mover_to_lake=fed)["mover"] is True
    assert "mover" not in _lake_args(external_mover_to_lake=False)
