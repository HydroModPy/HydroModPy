"""A project run reads its substratum from ``[data.substratum]``.

The domain is built during setup, before the data step, so the raster is read
from the configuration there. The run below stops at ``setup_process``: the
first step consuming the model phase, reached without a solver binary. The
geographic support is synthetic, so no terrain engine runs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import StepError

rasterio = pytest.importorskip("rasterio")

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "raster_substratum"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow_nwt"]

[workspace]
project_root = "{root}"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "raster_substratum"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[domain.depth_model]
kind = "raster"
quantity = "thickness"

[[data.substratum.sources]]
source = "custom"
path = "{raster}"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[display]
enabled = false
"""


def _thickness_raster(path: Path, *, xmax: float) -> Path:
    """A 30 m thickness on 50 m cells from x = 0 to *xmax*, y = 0 to 1000."""
    ncols = int(xmax / 50.0)
    profile = {
        "driver": "GTiff",
        "height": 20,
        "width": ncols,
        "count": 1,
        "dtype": "float64",
        "crs": "EPSG:2154",
        "transform": rasterio.transform.from_origin(0.0, 1000.0, 50.0, 50.0),
        "nodata": -9999.0,
    }
    with rasterio.open(str(path), "w", **profile) as sink:
        sink.write(np.full((20, ncols), 30.0), 1)
    return path


def _project(root: Path, raster: Path):
    from hydromodpy.project.facade import Project

    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), raster=raster.as_posix()),
        encoding="utf-8",
    )
    return Project(config_path, no_display=True)


def test_the_run_places_the_substratum_the_raster_declares(tmp_path: Path) -> None:
    project = _project(tmp_path, _thickness_raster(tmp_path / "thickness.tif", xmax=1000.0))
    try:
        project.simulate(until_step="setup_process")
        domain = project._ctx.setup.domain
        top = domain.surface_topo.as_array()
        bottom = domain.substratum.as_array()
    finally:
        project.close()

    np.testing.assert_allclose(bottom, top - 30.0)


def test_a_raster_that_misses_half_the_box_stops_the_run(tmp_path: Path) -> None:
    project = _project(tmp_path, _thickness_raster(tmp_path / "half.tif", xmax=500.0))
    try:
        # The step wraps the refusal and keeps its type in the message.
        with pytest.raises(StepError, match="DataContractViolation.*200 of the 400 cells"):
            project.simulate(until_step="setup_process")
    finally:
        project.close()
