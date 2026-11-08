"""Geometry net: invariant quantiles of the current triangle and Voronoi cells.

Two committed bundles: the radial island (near-uniform cells) and the graded
well-and-stream strip (cells from 4 m to 60 m). The refactor of the mesh engines
must keep these numbers: cell counts exactly, areas and quantiles within the
"Mesh characterization net" bands of ``tests/TOLERANCES.md``.
Five probe points per bundle pin the mesh in space: the quantiles are blind to a
mirrored or rotated mesh, the area and center of the cell under a fixed
coordinate are not. Refresh the golden on purpose with ``--update-goldens``.
"""

from __future__ import annotations

import pytest

from hydromodpy.project.trial_pipeline import fill_trial_pipeline
from tests.regression.mesh.mesh_net.mesh_net_helpers import (
    ABS_FLOOR,
    GEOMETRY_REL_BY_METRIC,
    GRADED_BUNDLE,
    ISLAND_BUNDLE,
    QUANTILE_REL,
    assert_within_band,
    bundle_probes,
    geometry_metrics,
    load_golden,
    triangle_mesh,
    voronoi_mesh,
    write_golden,
)

fill_trial_pipeline()

pytestmark = [pytest.mark.regression, pytest.mark.fast]

PRODUCERS = {"triangle": triangle_mesh, "voronoi": voronoi_mesh}


@pytest.mark.parametrize("bundle", [ISLAND_BUNDLE, GRADED_BUNDLE])
def test_mesh_geometry_matches_golden(bundle: str, update_goldens: bool) -> None:
    probes = bundle_probes(bundle)
    actual = {
        name: geometry_metrics(producer(bundle), probes) for name, producer in PRODUCERS.items()
    }
    golden_name = f"geometry_{bundle}.json"

    if update_goldens:
        write_golden(
            golden_name,
            {"bundle": bundle, "values": actual},
        )
        return

    assert_within_band(
        actual,
        load_golden(golden_name),
        band_rel=QUANTILE_REL,
        rel_by_metric=GEOMETRY_REL_BY_METRIC,
        floors=ABS_FLOOR,
    )
