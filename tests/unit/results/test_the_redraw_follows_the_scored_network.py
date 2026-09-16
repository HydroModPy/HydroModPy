"""``role`` picks which stored network the redraw scores against.

A calibration can score the mapped network (``"reference"``) or the one the
DEM was thresholded into (``"generated"``). The redraw must follow whichever
one a trial actually used, or a map disagrees with the counts it publishes.
The default stays ``"reference"`` so every existing caller is unaffected.
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from hydromodpy.results.derive.stream_network import (
    network_comparison_from_run,
    unavailable_reason_for_comparison,
)
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NY,
    cell,
    column_cells,
    comparison_run,
)

GENERATED_COLUMN = 4
"""Far from the axis, so a test can tell the two networks apart at a glance."""


def _run_with_role_specific_networks(**kwargs):
    """A run whose 'reference' and 'generated' networks sit on different columns.

    Seepage runs down the axis column, so it agrees with a 'reference' network
    drawn there and disagrees with a 'generated' one drawn on the far column.
    """
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)], **kwargs)
    reference = run.hydrographic_network("reference")
    generated_x = (GENERATED_COLUMN + 0.5) * CELL_M
    generated = gpd.GeoDataFrame(
        geometry=[LineString([(generated_x, 0.1 * CELL_M), (generated_x, (NY - 0.1) * CELL_M)])],
        crs=run.mesh.crs,
    )
    networks = {"reference": reference, "generated": generated}
    run.has_hydrographic_network = lambda role="generated": role in networks
    run.hydrographic_network = lambda role="generated": networks[role]
    return run


def _mapped_cells(comparison) -> list[int]:
    return sorted(int(index) for index in comparison.mapped.nonzero()[0])


def test_default_role_is_reference() -> None:
    run = _run_with_role_specific_networks()

    comparison = network_comparison_from_run(run)

    assert _mapped_cells(comparison) == column_cells(AXIS_COLUMN)


def test_asking_for_generated_reaches_the_generated_network() -> None:
    run = _run_with_role_specific_networks()

    comparison = network_comparison_from_run(run, role="generated")

    assert _mapped_cells(comparison) == column_cells(GENERATED_COLUMN)


def test_unavailable_reason_follows_the_requested_role() -> None:
    run = _run_with_role_specific_networks()
    run.has_hydrographic_network = lambda role="generated": role == "reference"

    assert unavailable_reason_for_comparison(run) is None
    reason = unavailable_reason_for_comparison(run, role="generated")

    assert reason is not None
    assert "generated" in reason
