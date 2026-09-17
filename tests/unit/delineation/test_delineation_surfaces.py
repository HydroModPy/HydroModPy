"""Tests for the delineation surface actually consumed by callers.

The production contract is the three thematic sub-backends reached through
``WhiteboxWorkflowsBackend.raster`` / ``.flow`` / ``.delineation``. The
four-method ``DelineationBackend`` Protocol that used to sit above them
declared none of these members and had no caller; it is gone.
"""

from __future__ import annotations

from hydromodpy.spatial.delineation import (
    WhiteboxDelineationBackend,
    WhiteboxFlowBackend,
    WhiteboxRasterBackend,
)


def test_whitebox_split_backends_expose_thematic_surfaces() -> None:
    for name in ("read_raster", "write_raster", "clip_raster_to_polygon"):
        assert hasattr(WhiteboxRasterBackend, name)
    for name in ("fill_depressions", "breach_depressions", "d8_pointer", "d8_flow_accumulation"):
        assert hasattr(WhiteboxFlowBackend, name)
    for name in ("watershed", "extract_streams", "snap_pour_points"):
        assert hasattr(WhiteboxDelineationBackend, name)
