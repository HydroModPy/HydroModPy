from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import RunBuilder, runs

__all__ = ["runs"]


def _make_dem(nrow: int = 5, ncol: int = 4) -> np.ndarray:
    """Synthetic DEM: positive inside a rectangular catchment, -9999 outside."""
    dem = np.full((nrow, ncol), -9999.0, dtype="float64")
    dem[1:-1, 1:-1] = 100.0
    return dem


def _utc(day: str | None):
    """The instant a run records for a calendar day: midnight UTC."""
    return None if day is None else pd.Timestamp(day, tz="UTC").to_pydatetime()


def _register_sim(
    runs: RunBuilder,
    *,
    mesh_topology: str = "structured_3d",
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
    sid = runs.open(
        project="grid_test",
        mesh_topology=mesh_topology,
        n_cells=nrow * ncol,
        n_layers=1,
        n_timesteps=n_timesteps,
        period_start=_utc(period_start),
        period_end=_utc(period_end),
    ).sim_id
    if with_metadata:
        meta = {
            "dem_res": str(dem_res),
            "nrow": str(nrow),
            "ncol": str(ncol),
            "crs_proj": "+proj=lcc +lat_1=49 +lat_2=44",
            "catch_area": str(catch_area_km2),
        }
        runs.store(sid).write_geographic_metadata(sid, meta)
    if with_raster:
        dem = _make_dem(nrow, ncol)
        transform = (dem_res, 0.0, xmin, 0.0, -dem_res, ymax)
        runs.store(sid).write_geographic_raster(
            sid,
            "watershed_dem",
            dem,
            transform=transform,
            crs="+proj=lcc",
            nodata=-9999.0,
        )
    return sid


class TestGrid:
    def test_grid_scalar_metadata(self, runs):
        sid = _register_sim(
            runs,
            dem_res=50.0,
            nrow=5,
            ncol=4,
            xmin=300_000.0,
            ymax=6_800_000.0,
            catch_area_km2=12.5,
        )
        run = Run(sid, runs.reader())
        grid = run.grid

        assert grid.cell_size == 50.0
        assert grid.shape == (5, 4)
        assert grid.crs == "+proj=lcc +lat_1=49 +lat_2=44"
        assert grid.catchment_area_m2 == 12.5 * 1e6

    def test_grid_extent_matches_dem_transform(self, runs):
        sid = _register_sim(runs, dem_res=50.0, nrow=5, ncol=4, xmin=300_000.0, ymax=6_800_000.0)
        run = Run(sid, runs.reader())
        xmin, xmax, ymin, ymax = run.grid.extent

        assert xmin == 300_000.0
        assert xmax == 300_000.0 + 4 * 50.0
        assert ymax == 6_800_000.0
        assert ymin == 6_800_000.0 - 5 * 50.0

    def test_grid_is_cached(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        assert run.grid is run.grid

    def test_grid_raises_on_lumped(self, runs):
        sid = runs.open(
            project="grid_test", solver="gr4j", solver_category="lumped", n_cells=1, n_layers=1
        ).sim_id
        run = Run(sid, runs.reader())
        with pytest.raises(RuntimeError, match="lumped simulation has no spatial grid"):
            _ = run.grid

    def test_grid_raises_on_missing_metadata(self, runs):
        sid = _register_sim(runs, with_metadata=False)
        run = Run(sid, runs.reader())
        with pytest.raises(RuntimeError, match="Grid metadata incomplete"):
            _ = run.grid


class TestCatchmentMask:
    def test_mask_from_dem(self, runs):
        sid = _register_sim(runs, nrow=5, ncol=4)
        run = Run(sid, runs.reader())
        mask = run.catchment_mask

        assert mask.shape == (5, 4)
        assert mask.dtype == bool
        expected = np.zeros((5, 4), dtype=bool)
        expected[1:-1, 1:-1] = True
        np.testing.assert_array_equal(mask, expected)

    def test_mask_is_cached(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        assert run.catchment_mask is run.catchment_mask

    def test_mask_area_consistency(self, runs):
        sid = _register_sim(runs, dem_res=50.0, nrow=5, ncol=4)
        run = Run(sid, runs.reader())
        mask_area = int(run.catchment_mask.sum()) * run.grid.cell_size**2
        assert mask_area == (3 * 2) * 2500.0


class TestCatchmentMaskFromTheStoredBasin:
    @staticmethod
    def _store_basin(runs, sid, cells, n=20, rule="near_point"):
        descent_zeros = np.zeros(n, dtype=bool)
        basin = descent_zeros.copy()
        basin[cells] = True
        sz = runs.store(sid).open_zarr(sid)
        try:
            sz.write_descent(
                receiver=np.full(n, -1, dtype=np.int64),
                surface=np.zeros(n),
                base_level=descent_zeros,
                constant_head=descent_zeros,
                raised=descent_zeros,
                channel=descent_zeros,
                pinned=descent_zeros,
                attrs={},
                basin=basin,
                basin_attrs={"descent_outlet": cells[0], "basin_rule": rule},
            )
        finally:
            sz.close()

    def test_mask_is_the_stored_basin_one_value_per_face(self, runs, caplog):
        sid = _register_sim(runs, nrow=5, ncol=4)
        self._store_basin(runs, sid, [6, 7, 10])

        with caplog.at_level("INFO"):
            mask = Run(sid, runs.reader()).catchment_mask

        assert mask.shape == (20,)
        assert mask.dtype == bool
        assert np.flatnonzero(mask).tolist() == [6, 7, 10]
        assert not mask.flags.writeable
        assert "predates the stored basin" not in caplog.text

    def test_the_largest_basin_of_a_synthetic_domain_is_no_catchment(self, runs, caplog):
        sid = _register_sim(runs, nrow=5, ncol=4)
        self._store_basin(runs, sid, [6, 7, 10], rule="largest_basin")

        with caplog.at_level("INFO"):
            mask = Run(sid, runs.reader()).catchment_mask

        assert mask.shape == (5, 4)
        assert "no catchment" in caplog.text
        assert "'dem_raster'" in caplog.text

    def test_mask_is_cached(self, runs):
        sid = _register_sim(runs)
        self._store_basin(runs, sid, [6])
        run = Run(sid, runs.reader())
        assert run.catchment_mask is run.catchment_mask

    def test_a_run_without_a_basin_falls_back_on_the_dem_and_says_so_once(self, runs, caplog):
        sid = _register_sim(runs, nrow=5, ncol=4)
        run = Run(sid, runs.reader())

        with caplog.at_level("INFO"):
            first = run.catchment_mask
            second = run.catchment_mask

        assert first is second
        assert first.shape == (5, 4)
        lines = [r for r in caplog.records if "predates the stored basin" in r.getMessage()]
        assert len(lines) == 1
        assert lines[0].levelno == logging.INFO
        assert "'dem_raster'" in lines[0].getMessage()
        assert "(5, 4)" in lines[0].getMessage()


class TestDem:
    def test_dem_masks_nodata_to_nan(self, runs):
        sid = _register_sim(runs, nrow=5, ncol=4)
        run = Run(sid, runs.reader())
        dem = run.dem

        assert dem.dtype == np.float64
        assert dem.shape == (5, 4)
        nan_cells = np.isnan(dem)
        valid_cells = ~nan_cells
        expected_valid = np.zeros((5, 4), dtype=bool)
        expected_valid[1:-1, 1:-1] = True
        np.testing.assert_array_equal(valid_cells, expected_valid)
        assert np.all(dem[valid_cells] == 100.0)

    def test_dem_does_not_mutate_stored_raster(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        _ = run.dem
        raster = run.geographic_raster("watershed_dem")
        assert raster.data[0, 0] == -9999.0

    def test_dem_is_cached(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        assert run.dem is run.dem


class TestFields:
    def _register_with_fields(
        self,
        runs,
        *,
        nrow=5,
        ncol=4,
        n_timesteps=3,
        variable="head",
    ):
        sid = _register_sim(
            runs,
            nrow=nrow,
            ncol=ncol,
            n_timesteps=n_timesteps,
        )
        sz = runs.store(sid).open_zarr(sid)
        n_cells = nrow * ncol
        for t in range(n_timesteps):
            values = np.arange(
                t * n_cells,
                (t + 1) * n_cells,
                dtype="float64",
            )
            sz.write_field(variable, t, values, n_timesteps=n_timesteps)
        return sid

    def test_xarray_batch_shape(self, runs):
        sid = self._register_with_fields(runs, nrow=5, ncol=4, n_timesteps=3)
        run = Run(sid, runs.reader())
        ds = run.array.to_xarray_batch(("head",))
        assert "head" in ds.data_vars
        assert ds["head"].dims == ("time", "layer", "cell")
        assert ds["head"].shape == (3, 1, 20)

    def test_xarray_batch_values_match_field(self, runs):
        sid = self._register_with_fields(runs, nrow=5, ncol=4, n_timesteps=3)
        run = Run(sid, runs.reader())
        ds = run.array.to_xarray_batch(("head",))
        for t in range(3):
            frame = np.asarray(run.field("head", timestep=t)).ravel()
            np.testing.assert_array_equal(ds["head"].isel(time=t, layer=0).values, frame)

    def test_list_fields_lists_readable_registry_names(self, runs):
        sid = self._register_with_fields(runs, nrow=5, ncol=4, n_timesteps=3)
        n_cells = 5 * 4
        sz = runs.store(sid).open_zarr(sid)
        for t in range(3):
            sz.write_field("watertable_depth", t, np.ones(n_cells), n_timesteps=3)
        run = Run(sid, runs.reader())

        fields = run.array.list_fields()
        # Persisted names plus the head-derived fields rebuilt on read. This
        # store has no surface elevation, so depth and seepage stay out.
        assert fields == ["head", "watertable_depth", "watertable_elevation"]
        # every listed name is readable through run.field
        for name in fields:
            assert run.field(name, timestep=0).size == n_cells


class TestTimeIndex:
    def test_time_index_basic(self, runs):
        # The run keeps the window [first boundary, last boundary), the
        # last one exclusive, and the solvers stamp each period at its end.
        # This fallback used to spread 36 stamps evenly from the window start,
        # which matched neither the solver axis nor the calendar.
        sid = _register_sim(
            runs,
            n_timesteps=36,
            period_start="2000-01-01",
            period_end="2003-01-01",
        )
        run = Run(sid, runs.reader())
        idx = run.time_index
        assert isinstance(idx, pd.DatetimeIndex)
        assert len(idx) == 36
        assert idx.equals(pd.date_range("2000-02-01", "2003-01-01", freq="MS").as_unit("ns"))

    def test_time_index_is_cached(self, runs):
        sid = _register_sim(
            runs,
            n_timesteps=5,
            period_start="2000-01-01",
            period_end="2000-01-05",
        )
        run = Run(sid, runs.reader())
        assert run.time_index is run.time_index

    def test_time_index_missing_period_raises(self, runs):
        sid = _register_sim(runs, n_timesteps=5)
        run = Run(sid, runs.reader())
        with pytest.raises(RuntimeError, match="period_start/period_end"):
            _ = run.time_index


class TestParams:
    def test_params_returns_global_scalars(self, runs):
        sid = _register_sim(runs)
        runs.store(sid).write_parameters(
            sid, [{"param_name": "K", "value": 5e-5}, {"param_name": "Sy", "value": 0.05}]
        )
        run = Run(sid, runs.reader())
        assert run.params == {"K": 5e-5, "Sy": 0.05}

    def test_params_excludes_zonal_rows(self, runs):
        sid = _register_sim(runs)
        runs.store(sid).write_parameters(
            sid,
            [
                {"param_name": "thickness", "value": 30.0},
                {"param_name": "K", "zone_id": "zone_1", "value": 1e-4},
                {"param_name": "K", "zone_id": "zone_2", "value": 2e-4},
            ],
        )
        run = Run(sid, runs.reader())
        assert run.params == {"thickness": 30.0}


class TestOutlet:
    def test_outlet_returns_xy(self, runs):
        sid = _register_sim(runs)
        runs.store(sid).write_geographic_metadata(
            sid,
            {"x_outlet": "300500.0", "y_outlet": "6795000.0"},
        )
        run = Run(sid, runs.reader())
        assert run.outlet == (300500.0, 6795000.0)

    def test_outlet_missing_raises(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        with pytest.raises(RuntimeError, match="Outlet coordinates missing"):
            _ = run.outlet
