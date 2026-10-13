"""A vector geology map reaches the solver K as exact zone areas.

The geology field built from a vector file keeps its polygons, reprojected to
the model CRS and cut to the raster support. The MODFLOW mapping reads them: a
cell the contact crosses takes the area-weighted mean of the two zone values,
where the encoded raster would give the zone of its pixel centres.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import box

from hydromodpy.data.variables.geology.field import build_geology_field
from hydromodpy.solver.modflow_common.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.raster_support import RasterSupport
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

CONTACT_X = 352_000.0
SUPPORT = RasterSupport(
    crs="EPSG:2154",
    dx=100.0,
    dy=100.0,
    xmin=350_500.0,
    xmax=353_500.0,
    ymin=6_780_500.0,
    ymax=6_783_500.0,
    nrows=30,
    ncols=30,
)


def _geology_field(tmp_path: Path) -> object:
    """Two units side by side, written in WGS84 to force a reprojection."""
    units = gpd.GeoDataFrame(
        {"CODE": ["A", "B"]},
        geometry=[
            box(350_000.0, 6_780_000.0, CONTACT_X, 6_784_000.0),
            box(CONTACT_X, 6_780_000.0, 354_000.0, 6_784_000.0),
        ],
        crs="EPSG:2154",
    )
    path = tmp_path / "units.gpkg"
    units.to_crs("EPSG:4326").to_file(str(path), driver="GPKG")
    return build_geology_field(
        SimpleNamespace(data=str(path), source="custom"),
        geology_cfg=SimpleNamespace(
            id="geology",
            cell_samples_per_axis=8,
            sources=[SimpleNamespace(source="custom", code_field="CODE")],
        ),
        raster_support=SUPPORT,
    )


def test_a_vector_geology_field_keeps_its_polygons_in_the_model_crs(tmp_path: Path) -> None:
    field = _geology_field(tmp_path)

    polygons = field.zone_polygons
    assert polygons.zone_keys == field.zone_keys == ("A", "B")
    xmin, ymin, xmax, ymax = shapely.total_bounds(polygons.geometries)
    # Reprojected back to Lambert-93 and cut to the support box.
    np.testing.assert_allclose(
        [xmin, ymin, xmax, ymax],
        [SUPPORT.xmin, SUPPORT.ymin, SUPPORT.xmax, SUPPORT.ymax],
        atol=1e-3,
    )
    areas = {
        key: float(shapely.area(polygons.geometries[polygons.zone_index == index]).sum())
        for index, key in enumerate(polygons.zone_keys)
    }
    assert abs(areas["A"] - (CONTACT_X - SUPPORT.xmin) * 3000.0) < 1.0
    assert abs(areas["B"] - (SUPPORT.xmax - CONTACT_X) * 3000.0) < 1.0


def test_a_cell_the_contact_crosses_takes_the_area_mean_of_the_two_values(
    tmp_path: Path,
) -> None:
    field = _geology_field(tmp_path)
    # Columns of 300 m from x = 351 050: the last one, [351 950, 352 250], is 1/6 A.
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=4,
        top=np.full((2, 4), 10.0),
        botm=np.full((1, 2, 4), 0.0),
        dx=300.0,
        dy=300.0,
        xoff=351_050.0,
        yoff=6_781_000.0,
    )
    k_a, k_b = 1.0e-4, 1.0e-6
    flow = SimpleNamespace(
        parameters={
            "K": FieldParam(
                identifier="K",
                kind="heterogeneous",
                values_by_key={"A": k_a, "B": k_b},
                field_spatial_id="geology",
            )
        }
    )

    out = resolve_flow_property_arrays(
        flow=flow,
        domain=SimpleNamespace(zones={"geology": field}),
        solver_mesh=solver_mesh,
        required_properties={"K"},
    )

    mixed = (50.0 * k_a + 250.0 * k_b) / 300.0
    expected = np.tile([k_a, k_a, k_a, mixed], 2)
    np.testing.assert_allclose(out["hk_value"], expected, rtol=1e-9)
    np.testing.assert_allclose(out["hk"], expected[None, :], rtol=1e-9)
