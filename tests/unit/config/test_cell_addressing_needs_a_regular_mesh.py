"""A ``[lay, row, col]`` address is refused while the file loads when the mesh has no rows.

Only the ``regular`` engine has rows and columns. A well or an explicit SFR reach that
names its cell that way on a triangle or Voronoi mesh would stop the build after the
meshing; the configuration refuses it before any step, and names where the address is.
"""

from __future__ import annotations

from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig

CELL = {"kind": "cell", "cell": [0, 1, 2]}
XY = {"kind": "absolute_xy", "x": 1.0, "y": 2.0}
REACH = {
    "cell": CELL,
    "length": "100 m",
    "width": "2 m",
    "slope": 0.001,
    "top": "10 m",
}


def _payload(
    mesh: dict[str, Any] | None,
    *,
    well: dict[str, Any] | None = None,
    reach: dict[str, Any] | None = None,
    solver: str = "modflow6",
) -> dict[str, Any]:
    flow: dict[str, Any] = {}
    if well is not None:
        flow["active_sinks_sources"] = ["wells"]
        flow["sinks_sources"] = {"wells": {"W1": {"location": well, "flux": -1.0}}}
    if reach is not None:
        flow["active_bc"] = ["sfr"]
        flow["sinks_sources"] = {"sfr": {"net": {"reaches": [reach]}}}
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": {"backend": solver}},
        "flow": flow,
    }
    if mesh is not None:
        payload["mesh"] = mesh
    return payload


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_well_addressed_by_row_and_column_is_refused_on_an_unstructured_engine(
    engine: str,
) -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_payload({"engine": engine}, well=CELL))
    message = str(excinfo.value)
    assert "flow.sinks_sources.wells.W1.location" in message
    assert f"mesh.engine is '{engine}'" in message
    assert "absolute_xy or relative_xy" in message


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_an_explicit_reach_addressed_by_row_and_column_is_refused_too(engine: str) -> None:
    with pytest.raises(ValueError, match=r"flow\.sinks_sources\.sfr\.net\.reaches\[0\]\.cell"):
        HydroModPyConfig.model_validate(_payload({"engine": engine}, reach=REACH))


@pytest.mark.parametrize("mesh", [None, {"engine": "regular"}])
def test_the_regular_engine_and_the_default_one_keep_the_address(mesh) -> None:
    HydroModPyConfig.model_validate(_payload(mesh, well=CELL))
    HydroModPyConfig.model_validate(_payload(mesh, reach=REACH))


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_well_located_by_coordinates_loads_on_every_engine(engine: str) -> None:
    HydroModPyConfig.model_validate(_payload({"engine": engine}, well=XY))


def test_every_address_of_the_file_is_named_at_once() -> None:
    payload = _payload({"engine": "triangle"}, well=CELL)
    payload["flow"]["active_bc"] = ["sfr"]
    payload["flow"]["sinks_sources"]["sfr"] = {"net": {"reaches": [REACH]}}

    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(payload)
    message = str(excinfo.value)
    assert "wells.W1.location" in message
    assert "sfr.net.reaches[0].cell" in message
