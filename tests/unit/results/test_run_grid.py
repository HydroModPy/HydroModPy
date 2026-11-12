from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.forcing.recharge_rates import CRITERION_MEAN_RECHARGE_ATTR
from hydromodpy.results.run.tables import global_parameters
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import RunBuilder, runs

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
    **facts: object,
) -> str:
    sid = runs.open(
        project="grid_test",
        mesh_topology=mesh_topology,
        n_cells=nrow * ncol,
        n_layers=1,
        n_timesteps=n_timesteps,
        period_start=_utc(period_start),
        period_end=_utc(period_end),
        **facts,
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
    def test_grid_is_cached(self, runs):
        sid = _register_sim(runs)
        run = Run(sid, runs.reader())
        assert run.grid is run.grid

    def test_grid_raises_on_missing_metadata(self, runs):
        sid = _register_sim(runs, with_metadata=False)
        run = Run(sid, runs.reader())
        with pytest.raises(RuntimeError, match="Grid metadata incomplete"):
            _ = run.grid


class TestCatchmentMask:
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
            frame = np.asarray(run.field("head", time=t)).ravel()
            np.testing.assert_array_equal(ds["head"].isel(time=t, layer=0).values, frame)


class TestParams:
    def test_params_returns_global_scalars(self, runs):
        sid = _register_sim(runs)
        runs.store(sid).write_parameters(
            sid, [{"param_name": "K", "value": 5e-5}, {"param_name": "Sy", "value": 0.05}]
        )
        run = Run(sid, runs.reader())
        assert global_parameters(run) == {"K": 5e-5, "Sy": 0.05}


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


class TestTheCriterionInputsTheRunKept:
    """The run holds what the stream criterion read, and its descent reads it back alone."""

    @staticmethod
    def _keep(runs, sid, *, open_water=(), outline=None, recharge=None, n=20):
        water = np.zeros(n, dtype=bool)
        water[list(open_water)] = True
        sz = runs.store(sid).open_zarr(sid)
        try:
            sz.write_criterion_cells(
                open_water=water, catchment_cells=None if outline is None else np.asarray(outline)
            )
            if recharge is not None:
                sz.write_forcing_attrs({CRITERION_MEAN_RECHARGE_ATTR: recharge})
        finally:
            sz.close()

    def test_a_run_that_kept_none_gives_none(self, runs):
        sid = _register_sim(runs, nrow=5, ncol=4)

        holder = Run(sid, runs.reader()).descent

        assert holder.open_water() is None
        assert holder.catchment_cells() is None
        assert holder.criterion_recharge() is None

    def test_a_run_without_an_outline_has_open_water_alone(self, runs):
        sid = _register_sim(runs, nrow=5, ncol=4)
        self._keep(runs, sid, open_water=[1])

        holder = Run(sid, runs.reader()).descent

        assert holder.open_water() is not None
        assert holder.catchment_cells() is None

    def test_the_recharge_is_the_number_the_run_kept(self, runs):
        sid = _register_sim(runs, nrow=5, ncol=4)
        self._keep(runs, sid, recharge=1.25e-8)

        assert Run(sid, runs.reader()).descent.criterion_recharge() == pytest.approx(1.25e-8)

    def test_each_input_is_read_once_and_without_loading_d(self, runs, monkeypatch):
        sid = _register_sim(runs, nrow=5, ncol=4)
        self._keep(runs, sid, open_water=[1], recharge=1.0e-8)
        holder = Run(sid, runs.reader()).descent
        from hydromodpy.results.run import descent as module

        first = holder.open_water()
        monkeypatch.setattr(
            module, "read_open_water", lambda run: pytest.fail("the mask was read twice")
        )

        assert holder.open_water() is first
        assert holder.criterion_recharge() == pytest.approx(1.0e-8)
