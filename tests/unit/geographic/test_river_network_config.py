"""``[geographic.river_network]``: the two threshold modes and their refusals."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic import GeographicConfig


def _network(**keys) -> GeographicConfig:
    return GeographicConfig.model_validate(
        {"source_mode": "synthetic", "river_network": {"enabled": True, **keys}}
    )


def test_an_area_threshold_and_a_cell_threshold_are_both_accepted() -> None:
    area = _network(
        threshold_mode="area_km2", threshold_area_km2=0.5, min_stream_length_m="250 m"
    ).river_network
    cells = _network(threshold_mode="cells", threshold_cells=2000).river_network

    assert (area.enabled, str(area.threshold_mode)) == (True, "area_km2")
    assert float(area.threshold_area_km2) == pytest.approx(0.5)
    assert float(area.min_stream_length_m) == pytest.approx(250.0)
    assert (cells.enabled, str(cells.threshold_mode)) == (True, "cells")
    assert float(cells.threshold_cells) == pytest.approx(2000.0)


@pytest.mark.parametrize(
    ("keys", "match"),
    [
        ({"threshold_mode": "cells"}, r"threshold_mode='cells'.*threshold_cells"),
        ({"threshold_mode": "area_km2"}, r"threshold_mode='area_km2'.*threshold_area_km2"),
        (
            {"threshold_mode": "area_km2", "threshold_area_km2": 0.0},
            r"threshold_area_km2 must be > 0",
        ),
        ({"threshold_mode": "cells", "threshold_cells": 0}, r"threshold_cells must be > 0"),
        (
            {"threshold_mode": "area_km2", "threshold_area_km2": 0.5, "threshold_cells": 10},
            r"threshold_cells must be omitted",
        ),
        (
            {"threshold_mode": "cells", "threshold_cells": 10, "threshold_area_km2": 0.5},
            r"threshold_area_km2 must be omitted",
        ),
        (
            {"threshold_mode": "area_km2", "threshold_area_km2": 0.5, "min_stream_length_m": -1.0},
            r"min_stream_length_m",
        ),
    ],
    ids=[
        "cells-without-its-value",
        "area-without-its-value",
        "area-zero",
        "cells-zero",
        "area-with-a-cell-count",
        "cells-with-an-area",
        "negative-min-stream-length",
    ],
)
def test_an_enabled_network_with_a_wrong_threshold_is_refused(keys, match) -> None:
    with pytest.raises(ValidationError, match=match):
        _network(**keys)


def test_a_jenson_snap_needs_a_threshold_to_draw_its_streams() -> None:
    catchment = {
        "catch_def": "from_outlet_coord",
        "dem_init_path": "dem.tif",
        "x_outlet": 1.0,
        "y_outlet": 2.0,
        "snap_dist": 50.0,
        "buff_area": "10%",
        "snap_method": "jenson",
    }

    with pytest.raises(ValidationError, match="snap_method = 'jenson'"):
        GeographicConfig.model_validate({"catchment": catchment})
    network = {"threshold_mode": "cells", "threshold_cells": 50}
    accepted = GeographicConfig.model_validate({"catchment": catchment, "river_network": network})
    assert accepted.snap_method == "jenson"
