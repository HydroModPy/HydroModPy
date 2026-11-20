"""Pipeline net: steady MODFLOW 6 heads on the triangle and Voronoi cells.

One short run per cell kind through the public ``hydromodpy run`` entry point
on the committed circular-island bundle, read back from the run store. The
requested mesh is the only thing the refactor may change (``[mesh_input]`` +
``grid_dual`` today). The recharge is a planar gradient raster, so the field is
not symmetric and a mirrored or rotated mesh moves the probe heads. Cell counts
are exact, areas and heads within the "Mesh characterization net" bands of
``tests/TOLERANCES.md``. Refresh the goldens on purpose with ``--update-goldens``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.regression.mesh.mesh_net.mesh_net_helpers import (
    HEAD_RANGE_REL,
    HEADS_REL_BY_METRIC,
    ISLAND_BUNDLE,
    assert_within_band,
    head_metrics,
    load_golden,
    read_run,
    run_fixture,
    write_golden,
)

pytestmark = [pytest.mark.regression, pytest.mark.fast, pytest.mark.mf6, pytest.mark.steady]


def _require_mf6() -> None:
    from hydromodpy.core.workspace.workspace import resolve_bin_path
    from hydromodpy.solver.modflow_common.binaries import locate_solver_binary

    if locate_solver_binary(Path(resolve_bin_path()), "mf6") is None:
        pytest.skip("mf6 is missing. Run `hmp install-binaries` first.")


@pytest.mark.parametrize("cells", ["triangle", "voronoi"])
def test_island_heads_match_golden(cells: str, update_goldens: bool, tmp_path: Path) -> None:
    _require_mf6()
    out_dir = tmp_path / f"net_{cells}"
    out_dir.mkdir()
    run_fixture(f"island_{cells}.toml", out_dir)
    actual = head_metrics(read_run(out_dir))
    golden_name = f"heads_island_{cells}.json"

    if update_goldens:
        write_golden(
            golden_name,
            {
                "bundle": ISLAND_BUNDLE,
                "fixture": f"island_{cells}.toml",
                "values": actual,
            },
        )
        return

    golden = load_golden(golden_name)
    head = golden["values"]["head"]
    assert_within_band(
        actual,
        golden,
        band_rel=HEAD_RANGE_REL,
        rel_by_metric=HEADS_REL_BY_METRIC,
        scale=head["max"] - head["min"],
    )
