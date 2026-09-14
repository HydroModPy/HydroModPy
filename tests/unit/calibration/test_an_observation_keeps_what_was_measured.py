"""An observation is a measurement, and the loader knew more about it than the cost did.

``PointRecord`` arrives from the data layer carrying the unit, the sampling
frequency, the station's position, the source it came from, and a quality
dictionary with the completeness and the number of gaps. ``ObservedSeries``, the
shape every cost read, kept three of those: an id, a variable name, and a pandas
series. Everything else was dropped on the floor, one layer after it had been
computed.

That loss is not cosmetic. A profile in metres below ground compared to a head in
absolute elevation is a defensible model scored against the wrong reference, and
nothing in the chain could notice because the unit had already been thrown away.
And the error model is what makes a weighted sum defensible at all: a residual
divided by what the instrument can actually resolve is a pure number, and pure
numbers add up.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.calibration.observations.record import ObservationRecord
from hydromodpy.data.contracts.timeseries import PointRecord


def _point(**over: object) -> PointRecord:
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2000-01-01", periods=5, freq="D"),
            "value": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    payload: dict[str, object] = {
        "station_id": "J7branch",
        "variable": "discharge",
        "source": "hydroportail",
        "unit": "m3/s",
        "frequency": "D",
        "data": frame,
        "date_start": datetime(2000, 1, 1),
        "date_end": datetime(2000, 1, 5),
    }
    payload.update(over)
    return PointRecord(**payload)  # type: ignore[arg-type]


class TestWhatItKeeps:
    def test_it_keeps_the_unit_the_loader_resolved(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        assert record.unit == "m3/s"

    def test_it_keeps_the_station_the_source_and_the_frequency(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        assert record.station_id == "J7branch"
        assert record.source == "hydroportail"
        assert record.frequency == "D"

    def test_it_keeps_the_series_as_a_dated_index(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        assert isinstance(record.series.index, pd.DatetimeIndex)
        assert list(record.series) == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_it_keeps_the_quality_the_loader_computed(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        assert record.completeness_pct is not None
        assert record.n_missing is not None


class TestTheErrorModel:
    def test_none_is_declared_by_default(self) -> None:
        """An error model is a statement about an instrument, never a guess."""
        record = ObservationRecord.from_point_record(_point())

        assert record.has_error_model is False

    def test_a_relative_error_is_a_share_of_the_value(self) -> None:
        record = ObservationRecord.from_point_record(_point(), error_relative=0.08)

        assert record.has_error_model is True
        assert record.sigma_at(5.0) == pytest.approx(0.4)

    def test_an_absolute_error_is_the_same_at_every_value(self) -> None:
        record = ObservationRecord.from_point_record(_point(), error_absolute=0.02)

        assert record.sigma_at(5.0) == pytest.approx(0.02)
        assert record.sigma_at(500.0) == pytest.approx(0.02)

    def test_the_two_together_take_the_larger(self) -> None:
        record = ObservationRecord.from_point_record(
            _point(), error_relative=0.08, error_absolute=0.5
        )

        assert record.sigma_at(1.0) == pytest.approx(0.5)
        assert record.sigma_at(100.0) == pytest.approx(8.0)

    def test_a_floor_stops_sigma_collapsing_at_low_flow(self) -> None:
        record = ObservationRecord.from_point_record(
            _point(), error_relative=0.08, error_floor=0.05
        )

        assert record.sigma_at(0.1) == pytest.approx(0.05)

    def test_asking_for_sigma_without_a_model_is_refused(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        with pytest.raises(ValueError, match="error model"):
            record.sigma_at(1.0)

    def test_a_negative_error_is_refused(self) -> None:
        with pytest.raises(ValueError):
            ObservationRecord.from_point_record(_point(), error_relative=-0.1)


class TestSampling:
    def test_a_regular_record_says_so(self) -> None:
        record = ObservationRecord.from_point_record(_point())

        assert record.sampling == "regular"

    def test_an_occasional_record_declares_its_date_tolerance(self) -> None:
        record = ObservationRecord.from_point_record(
            _point(), sampling="occasional", date_tolerance="2 days"
        )

        assert record.sampling == "occasional"
        assert record.date_tolerance == pd.Timedelta("2 days")

    def test_a_tolerance_without_occasional_sampling_is_refused(self) -> None:
        """It would be a setting nothing reads."""
        with pytest.raises(ValueError, match="occasional"):
            ObservationRecord.from_point_record(_point(), date_tolerance="2 days")
