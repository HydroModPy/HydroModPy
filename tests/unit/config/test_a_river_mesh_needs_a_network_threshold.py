"""A mesh along the rivers needs a river network threshold, named at check time.

The mesh switches [geographic.river_network] on by itself, so the threshold
check of that section never ran, and the run stopped at build_geographic
with "threshold_area_km2 must be > 0".
"""

from __future__ import annotations

from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig


def _payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"catchment": {"catch_def": "dem", "dem_init_path": "dem.tif"}},
        "mesh": {"engine": "voronoi"},
    }
    payload.update(sections)
    return payload


def test_a_river_mesh_without_a_threshold_is_refused_with_the_key() -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_payload())
    message = str(excinfo.value)
    assert "[mesh] engine = 'voronoi' with families.rivers = 'cell'" in message
    assert "Set threshold_area_km2 under [geographic.river_network]" in message


def test_a_river_mesh_with_a_threshold_loads() -> None:
    payload = _payload()
    payload["geographic"]["river_network"] = {"threshold_area_km2": 0.5}
    cfg = HydroModPyConfig.model_validate(payload)
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.families.rivers == "cell"


def test_a_cells_threshold_is_named_in_cells_mode() -> None:
    payload = _payload()
    payload["geographic"]["river_network"] = {"threshold_mode": "cells"}
    with pytest.raises(ValueError, match="Set threshold_cells under"):
        HydroModPyConfig.model_validate(payload)


def test_a_mesh_that_ignores_the_rivers_needs_no_threshold() -> None:
    payload = _payload(mesh={"engine": "voronoi", "families": {"rivers": "none"}})
    cfg = HydroModPyConfig.model_validate(payload)
    assert cfg.mesh.families.rivers == "none"


def test_the_regular_engine_needs_no_threshold() -> None:
    cfg = HydroModPyConfig.model_validate(_payload(mesh={"engine": "regular"}))
    assert cfg.mesh.engine == "regular"
