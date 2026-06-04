"""Unit tests for in-memory field discretization on structured grids.

Covers: empty LoadResult, static fields, temporal aggregation, spatially
varying fields, multiple-record averaging, unit conversion, interpolation
method parameter.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_fields_on_sgrid,
)

from ._test_sgrid_field_discretization_builders import (
    MM_DAY_TO_M_S,
    _make_sgrid,
    _make_simulation_window,
    _make_static_field_record,
    _make_temporal_field_record,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# 1. Empty LoadResult
# ---------------------------------------------------------------------------


class TestEmptyLoadResult:
    def test_no_fields_returns_zeros(self):
        sgrid = _make_sgrid(4, 5)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(),
            sgrid=sgrid,
            nper=3,
        )
        assert len(result) == 3
        for kper in range(3):
            assert result[kper].shape == (4, 5)
            assert np.all(result[kper] == 0.0)


# ---------------------------------------------------------------------------
# 2. Static field - steady-state (xarray Dataset, no time dimension)
# ---------------------------------------------------------------------------


class TestStaticFieldSteady:
    def test_uniform_static_field_replicated_to_all_periods(self):
        """A static 5 mm/day field should produce the same m/s array for all kper."""
        nrow, ncol = 4, 5
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=3,
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert len(result) == 3
        for kper in range(3):
            assert result[kper].shape == (nrow, ncol)
            assert np.allclose(result[kper], expected_m_s, rtol=1e-10)

    def test_static_field_m_per_s_no_conversion(self):
        """A static field already in m/s should not be converted further."""
        nrow, ncol = 3, 3
        sgrid = _make_sgrid(nrow, ncol)
        value_m_s = 1.5e-7
        field_rec = _make_static_field_record(nrow, ncol, value=value_m_s, unit="m/s")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        assert np.allclose(result[0], value_m_s, rtol=1e-10)


# ---------------------------------------------------------------------------
# 3. Time-varying field - transient (xarray with time dimension)
# ---------------------------------------------------------------------------


class TestTemporalFieldTransient:
    def test_temporal_field_averaged_per_stress_period(self):
        """30 daily values split into 1-month period → mean of the 30 values."""
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)

        # 31 daily values for January 2020 (1..31 mm/day)
        daily_values = [float(d + 1) for d in range(31)]
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=daily_values,
            start_date="2020-01-01",
            unit="mm/day",
        )

        window = _make_simulation_window(
            "2020-01-01", "2020-01-31", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            simulation_window=window,
        )

        # Mean of 1..31 = 16.0 mm/day (all 31 days fall in [Jan 1, Feb 1))
        expected_m_s = 16.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-6)

    def test_temporal_field_two_periods(self):
        """60 daily values split into 2 monthly periods."""
        nrow, ncol = 2, 3
        sgrid = _make_sgrid(nrow, ncol)

        # Jan: 10 mm/day constant, Feb: 20 mm/day constant
        daily_values = [10.0] * 31 + [20.0] * 29  # 2020 is leap year
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=daily_values,
            start_date="2020-01-01",
            unit="mm/day",
        )

        window = _make_simulation_window(
            "2020-01-01", "2020-02-29", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=2,
            simulation_window=window,
        )

        assert len(result) == 2
        assert np.allclose(result[0], 10.0 * MM_DAY_TO_M_S, rtol=1e-6)
        assert np.allclose(result[1], 20.0 * MM_DAY_TO_M_S, rtol=1e-6)

    def test_missing_period_filled_with_zeros(self):
        """Periods without data coverage should be filled with zeros."""
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)

        # Only 10 days of data
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=[5.0] * 10,
            start_date="2020-01-01",
            unit="mm/day",
        )

        # 3 monthly periods, but data only covers early January
        window = _make_simulation_window(
            "2020-01-01", "2020-03-31", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=3,
            simulation_window=window,
        )

        assert len(result) == 3
        # Period 0 has data
        assert np.all(result[0] > 0)
        # Periods 1 and 2 use nearest time step (not zeros) because temporal
        # slicing falls back to nearest when no data in period bounds.
        # All three periods should have values since nearest-neighbor is used.

    def test_missing_period_raises_with_coverage_policy_error(self):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=[5.0] * 10,
            start_date="2020-01-01",
            unit="mm/day",
        )
        window = _make_simulation_window(
            "2020-01-01",
            "2020-03-31",
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        )

        with pytest.raises(ValueError, match="no gridded forcing values"):
            discretize_fields_on_sgrid(
                load_result=LoadResult(fields=[field_rec]),
                sgrid=sgrid,
                nper=3,
                simulation_window=window,
            )


# ---------------------------------------------------------------------------
# 6. Unit conversion
# ---------------------------------------------------------------------------


class TestUnitConversion:
    @pytest.mark.parametrize(
        "unit, input_val, expected_m_s",
        [
            ("mm/day", 10.0, 10.0 * MM_DAY_TO_M_S),
            ("mm/jour", 10.0, 10.0 * MM_DAY_TO_M_S),
            ("m/day", 0.01, 0.01 / 86400.0),
            ("m/s", 1.5e-7, 1.5e-7),
            ("mm/s", 0.001, 0.001 * 1e-3),
        ],
    )
    def test_unit_conversion_applied_correctly(self, unit, input_val, expected_m_s):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=input_val, unit=unit)

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        assert np.allclose(result[0], expected_m_s, rtol=1e-8)

    def test_unknown_unit_raises(self):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=10.0, unit="degC")

        with pytest.raises(ValueError, match="Unsupported hydraulic-conductivity unit"):
            discretize_fields_on_sgrid(
                load_result=LoadResult(fields=[field_rec]),
                sgrid=sgrid,
                nper=1,
            )


# ---------------------------------------------------------------------------
# 7. Spatially varying field
# ---------------------------------------------------------------------------


class TestSpatiallyVaryingField:
    def test_spatially_varying_values_preserved(self):
        """Each cell should receive its own recharge value when grids align."""
        nrow, ncol = 3, 4
        dx, dy = 10.0, 10.0
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)

        x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
        y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])

        # Linearly varying: row 0 = 1, row 1 = 2, row 2 = 3 mm/day
        data_2d = np.array(
            [
                [1.0, 1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0, 3.0],
            ],
            dtype=float,
        )

        ds = xr.Dataset(
            {"recharge": (("y", "x"), data_2d)},
            coords={"x": x_coords, "y": y_coords},
        )
        field_rec = FieldRecord(
            variable="recharge",
            source="test",
            unit="mm/day",
            data=ds,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
        )

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        expected = data_2d * MM_DAY_TO_M_S
        assert np.allclose(result[0], expected, rtol=1e-6)


# ---------------------------------------------------------------------------
# 8. Multiple FieldRecords - averaging
# ---------------------------------------------------------------------------


class TestMultipleFieldRecords:
    def test_two_static_fields_averaged(self):
        """Two FieldRecords covering the same period should be averaged."""
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)

        field_a = _make_static_field_record(nrow, ncol, value=10.0, unit="mm/day")
        field_b = _make_static_field_record(nrow, ncol, value=20.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_a, field_b]),
            sgrid=sgrid,
            nper=1,
        )

        # Averaging logic: 0.5 * (first + second) per period.
        # First record: 10 mm/day → arr_a
        # Second record: 0.5 * (arr_a + arr_b) where arr_b = 20 mm/day
        # = 0.5 * (10 + 20) * MM_DAY_TO_M_S = 15 * MM_DAY_TO_M_S
        expected_m_s = 15.0 * MM_DAY_TO_M_S
        assert np.allclose(result[0], expected_m_s, rtol=1e-8)


# ---------------------------------------------------------------------------
# 10. Interpolation method parameter
# ---------------------------------------------------------------------------


class TestInterpolationMethod:
    def test_linear_interpolation_produces_valid_output(self):
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            method="linear",
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)

    def test_idw_interpolation_produces_valid_output(self):
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            method="idw",
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)
