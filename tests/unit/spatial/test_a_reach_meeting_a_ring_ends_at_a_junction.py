"""A reach meeting a closed ring ends at a junction, not at a source.

A pond outline drawn as a ring, or a line that loops back on itself, has no
free end. The point where a reach meets it is a junction: counted once, it
would be read as a head and start a stream at the pond.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("shapely")

from shapely.geometry import LineString  # noqa: E402

from hydromodpy.spatial.mesh.ops.network_heads import network_head_candidates  # noqa: E402

CRS = "EPSG:2154"


def test_a_reach_meeting_a_ring_ends_at_a_junction() -> None:
    pond = LineString([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    outflow = LineString([(0, 0), (-50, -50)])

    candidates = network_head_candidates([pond, outflow], mesh_crs=CRS, geometry_crs=CRS)

    np.testing.assert_allclose(candidates.head_xy, [[-50.0, -50.0]])


def test_a_line_looping_back_on_itself_has_one_free_end() -> None:
    lollipop = LineString([(0, 0), (100, 0), (100, 50), (50, 50), (50, 0)])

    candidates = network_head_candidates([lollipop], mesh_crs=CRS, geometry_crs=CRS)

    np.testing.assert_allclose(candidates.head_xy, [[0.0, 0.0]])
