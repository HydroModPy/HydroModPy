"""The stream raster takes numbers: a text or missing column is numbered instead."""

from __future__ import annotations

import pandas as pd

from hydromodpy.data.variables.hydrography.variable import numeric_raster_field


def test_a_numeric_column_is_kept() -> None:
    frame = pd.DataFrame({"FID": ["3", "7"]})
    assert numeric_raster_field(frame, "FID").tolist() == [3, 7]


def test_a_text_column_is_numbered_from_one() -> None:
    frame = pd.DataFrame({"code": ["04A0000", "04B0001", "04C0002"]})
    assert numeric_raster_field(frame, "code").tolist() == [1, 2, 3]
