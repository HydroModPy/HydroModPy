"""The MODFLOW 6 build reads its inputs from the ``Model`` it is bound to, and says what is missing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry, ModelTime
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.builders.period_forcing import simulation_window
from tests._helpers.model_factory import make_model, small_geometry

_RASTER = RasterGeometry.from_geographic(
    SimpleNamespace(watershed_buff_dem="buff.tif", watershed_box_buff_dem="box.tif")
)


def _geometry(*, domain=object(), raster=_RASTER, cells="mesh") -> Geometry:
    return Geometry(
        cells=small_geometry().cells if cells == "mesh" else cells, domain=domain, raster=raster
    )


def _bound(**members) -> SimpleNamespace:
    return SimpleNamespace(inputs=make_model(**members))


@pytest.mark.parametrize(("box", "path"), [(True, "box.tif"), (False, "buff.tif")])
def test_the_dem_follows_the_box_option(box: bool, path: str) -> None:
    model = _bound(geometry=_geometry())

    build.select_active_dem(model, box=box)

    assert model.dem_watershed_path == path


def test_a_model_without_a_dem_grid_is_refused_by_name() -> None:
    model = _bound(geometry=_geometry(raster=None))

    with pytest.raises(ValueError, match=r"Model\.geometry\.raster"):
        build.select_active_dem(model, box=True)
    with pytest.raises(ValueError, match=r"Model\.geometry\.raster"):
        build.ensure_solver_routing_context(
            SimpleNamespace(
                inputs=model.inputs, routing_ctx=None, grid_ctx=object(), full_path=".", sink=None
            )
        )


VALIDATION_CASES = (
    ("no model", SimpleNamespace(inputs=None), "requires a Model object"),
    ("no domain", _bound(geometry=_geometry(domain=None)), "requires a configured Domain object"),
    (
        "transient run without a time grid",
        _bound(
            geometry=_geometry(),
            time=ModelTime(grid=None, regime="transient", first_period_steady=True),
        ),
        "requires preprocess_options.time_grid",
    ),
)


@pytest.mark.parametrize(
    ("case", "model", "message"), VALIDATION_CASES, ids=[case[0] for case in VALIDATION_CASES]
)
def test_a_model_that_is_not_ready_is_refused(case: str, model, message: str) -> None:
    del case

    with pytest.raises(ValueError, match=message):
        build.validate_pre_processing_inputs(model)


def test_a_steady_model_needs_no_time_grid() -> None:
    model = _bound(geometry=_geometry())

    assert build.validate_pre_processing_inputs(model) is None


def test_a_model_without_a_cell_mesh_is_refused_before_the_grid_is_built() -> None:
    model = _bound(geometry=_geometry(cells=None))

    with pytest.raises(MeshError, match=r"Model\.geometry\.cells"):
        build._discretize_space(model)


def test_the_simulation_window_is_the_one_of_the_time_grid() -> None:
    window = object()
    dated = _bound(
        time=ModelTime(
            grid=SimpleNamespace(window=window), regime="transient", first_period_steady=True
        )
    )

    assert simulation_window(dated) is window
    assert simulation_window(_bound()) is None
