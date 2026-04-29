from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _make_dem(nrow: int = 5, ncol: int = 4) -> np.ndarray:
    """Synthetic DEM: positive inside a rectangular catchment, -9999 outside."""
    dem = np.full((nrow, ncol), -9999.0, dtype="float64")
    dem[1:-1, 1:-1] = 100.0
    return dem


def _register_sim(
    catalog: SimulationCatalog,
    *,
    mesh_topology: str = "dis",
    with_metadata: bool = True,
    with_raster: bool = True,
    dem_res: float = 50.0,
    catch_area_km2: float = 12.5,
    xmin: float = 300_000.0,
    ymax: float = 6_800_000.0,
    nrow: int = 5,
    ncol: int = 4,
    n_timesteps: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid,
        project="grid_test",
        solver="modflow6",
        mesh_topology=mesh_topology,
        n_cells=nrow * ncol,
        n_layers=1,
        n_timesteps=n_timesteps,
        period_start=period_start,
        period_end=period_end,
    )
    if with_metadata:
        meta = {
            "dem_res": str(dem_res),
            "nrow": str(nrow),
            "ncol": str(ncol),
            "crs_proj": "+proj=lcc +lat_1=49 +lat_2=44",
            "catch_area": str(catch_area_km2),
        }
        catalog.write_geographic_metadata(sid, meta)
    if with_raster:
        dem = _make_dem(nrow, ncol)
        transform = (dem_res, 0.0, xmin, 0.0, -dem_res, ymax)
        catalog.write_geographic_raster(
            sid,
            "watershed_dem",
            dem,
            transform=transform,
            crs="+proj=lcc",
            nodata=-9999.0,
        )
    return sid


class TestGrid:
    def test_grid_scalar_metadata(self, catalog):
        sid = _register_sim(
            catalog,
            dem_res=50.0,
            nrow=5,
            ncol=4,
            xmin=300_000.0,
            ymax=6_800_000.0,
            catch_area_km2=12.5,
        )
        run = Run(sid, catalog)
        grid = run.grid

        assert grid.cell_size == 50.0
        assert grid.shape == (5, 4)
        assert grid.crs == "+proj=lcc +lat_1=49 +lat_2=44"
        assert grid.catchment_area_m2 == 12.5 * 1e6

    def test_grid_extent_matches_dem_transform(self, catalog):
        sid = _register_sim(catalog, dem_res=50.0, nrow=5, ncol=4, xmin=300_000.0, ymax=6_800_000.0)
        run = Run(sid, catalog)
        xmin, xmax, ymin, ymax = run.grid.extent

        assert xmin == 300_000.0
        assert xmax == 300_000.0 + 4 * 50.0
        assert ymax == 6_800_000.0
        assert ymin == 6_800_000.0 - 5 * 50.0

    def test_grid_is_cached(self, catalog):
        sid = _register_sim(catalog)
        run = Run(sid, catalog)
        assert run.grid is run.grid

    def test_grid_raises_on_disu(self, catalog):
        sid = _register_sim(catalog, mesh_topology="disu")
        run = Run(sid, catalog)
        with pytest.raises(RuntimeError, match="unstructured mesh"):
            _ = run.grid

    def test_grid_raises_on_missing_metadata(self, catalog):
        sid = _register_sim(catalog, with_metadata=False)
        run = Run(sid, catalog)
        with pytest.raises(RuntimeError, match="Grid metadata incomplete"):
            _ = run.grid


class TestCatchmentMask:
    def test_mask_from_dem(self, catalog):
        sid = _register_sim(catalog, nrow=5, ncol=4)
        run = Run(sid, catalog)
        mask = run.catchment_mask

        assert mask.shape == (5, 4)
        assert mask.dtype == bool
        expected = np.zeros((5, 4), dtype=bool)
        expected[1:-1, 1:-1] = True
        np.testing.assert_array_equal(mask, expected)

    def test_mask_is_cached(self, catalog):
        sid = _register_sim(catalog)
        run = Run(sid, catalog)
        assert run.catchment_mask is run.catchment_mask

    def test_mask_area_consistency(self, catalog):
        sid = _register_sim(catalog, dem_res=50.0, nrow=5, ncol=4)
        run = Run(sid, catalog)
        mask_area = int(run.catchment_mask.sum()) * run.grid.cell_size**2
        assert mask_area == (3 * 2) * 2500.0


class TestDem:
    def test_dem_masks_nodata_to_nan(self, catalog):
        sid = _register_sim(catalog, nrow=5, ncol=4)
        run = Run(sid, catalog)
        dem = run.dem

        assert dem.dtype == np.float64
        assert dem.shape == (5, 4)
        nan_cells = np.isnan(dem)
        valid_cells = ~nan_cells
        expected_valid = np.zeros((5, 4), dtype=bool)
        expected_valid[1:-1, 1:-1] = True
        np.testing.assert_array_equal(valid_cells, expected_valid)
        assert np.all(dem[valid_cells] == 100.0)

    def test_dem_does_not_mutate_stored_raster(self, catalog):
        sid = _register_sim(catalog)
        run = Run(sid, catalog)
        _ = run.dem
        raster = run.geographic_raster("watershed_dem")
        assert raster.data[0, 0] == -9999.0

    def test_dem_is_cached(self, catalog):
        sid = _register_sim(catalog)
        run = Run(sid, catalog)
        assert run.dem is run.dem


class TestFields:
    def _register_with_fields(
        self,
        catalog,
        *,
        nrow=5,
        ncol=4,
        n_timesteps=3,
        variable="head",
    ):
        sid = _register_sim(
            catalog,
            nrow=nrow,
            ncol=ncol,
            n_timesteps=n_timesteps,
        )
        sz = catalog.open_zarr(sid)
        n_cells = nrow * ncol
        for t in range(n_timesteps):
            values = np.arange(
                t * n_cells,
                (t + 1) * n_cells,
                dtype="float64",
            )
            sz.write_field(variable, t, values, n_timesteps=n_timesteps)
        return sid

    def test_fields_stack_shape(self, catalog):
        from hydromodpy.results.contracts import Stack

        sid = self._register_with_fields(catalog, nrow=5, ncol=4, n_timesteps=3)
        run = Run(sid, catalog)
        stack = run.fields("head")
        assert isinstance(stack, Stack)
        assert stack.variable == "head"
        assert stack.data.shape == (3, 5, 4)

    def test_fields_values_match_field(self, catalog):
        sid = self._register_with_fields(catalog, nrow=5, ncol=4, n_timesteps=3)
        run = Run(sid, catalog)
        stack = run.fields("head")
        for t in range(3):
            frame = np.asarray(run.field("head", timestep=t)).reshape(5, 4)
            np.testing.assert_array_equal(stack.data[t], frame)


class TestTimeIndex:
    def test_time_index_basic(self, catalog):
        sid = _register_sim(
            catalog,
            n_timesteps=36,
            period_start="2000-01-01",
            period_end="2002-12-31",
        )
        run = Run(sid, catalog)
        idx = run.time_index
        assert isinstance(idx, pd.DatetimeIndex)
        assert len(idx) == 36
        assert idx[0] == pd.Timestamp("2000-01-01")
        assert idx[-1] == pd.Timestamp("2002-12-31")

    def test_time_index_is_cached(self, catalog):
        sid = _register_sim(
            catalog,
            n_timesteps=5,
            period_start="2000-01-01",
            period_end="2000-01-05",
        )
        run = Run(sid, catalog)
        assert run.time_index is run.time_index

    def test_time_index_missing_period_raises(self, catalog):
        sid = _register_sim(catalog, n_timesteps=5)
        run = Run(sid, catalog)
        with pytest.raises(RuntimeError, match="period_start/period_end"):
            _ = run.time_index


class TestParams:
    def test_params_returns_global_scalars(self, catalog):
        sid = _register_sim(catalog)
        catalog.connection.execute(
            "INSERT INTO parameters (sim_id, param_name, zone_id, value) "
            "VALUES (?, 'K', '__global__', 5e-5), "
            "       (?, 'Sy', '__global__', 0.05)",
            [sid, sid],
        )
        run = Run(sid, catalog)
        assert run.params == {"K": 5e-5, "Sy": 0.05}

    def test_params_excludes_zonal_rows(self, catalog):
        sid = _register_sim(catalog)
        catalog.connection.execute(
            "INSERT INTO parameters (sim_id, param_name, zone_id, value) "
            "VALUES (?, 'thickness', '__global__', 30.0), "
            "       (?, 'K', 'zone_1', 1e-4), "
            "       (?, 'K', 'zone_2', 2e-4)",
            [sid, sid, sid],
        )
        run = Run(sid, catalog)
        assert run.params == {"thickness": 30.0}


class TestOutlet:
    def test_outlet_returns_xy(self, catalog):
        sid = _register_sim(catalog)
        catalog.write_geographic_metadata(
            sid,
            {"x_outlet": "300500.0", "y_outlet": "6795000.0"},
        )
        run = Run(sid, catalog)
        assert run.outlet == (300500.0, 6795000.0)

    def test_outlet_missing_raises(self, catalog):
        sid = _register_sim(catalog)
        run = Run(sid, catalog)
        with pytest.raises(RuntimeError, match="Outlet coordinates missing"):
            _ = run.outlet
