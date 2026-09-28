"""A point output that observes a station is placed by the station's record.

The x and y written beside ``observes`` are not read, yet ``--list-phases``
printed them as where the discharge came from, and for Nancon the discharge is
the whole-catchment series. The listing now says what the run reads, and
loading warns about a position nobody reads, unless a snap may fall back on it.
"""

from __future__ import annotations

import warnings

import pytest

from hydromodpy.calibration.config import CalibOutputPoint, CalibrationConfig
from hydromodpy.calibration.runners.staged_runner import objective_comparison_table


def _point(**fields: object) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate({"support": "point", **fields})


def test_x_and_y_beside_observes_are_warned_as_ignored() -> None:
    with pytest.warns(UserWarning, match="observes station 'NANCON' and also writes x, y"):
        _point(variable="discharge", observes="NANCON", x=389285.91, y=6816518.749)


def test_a_geometry_beside_observes_is_warned_as_ignored() -> None:
    geometry = {"type": "Point", "coordinates": [0.0, 0.0]}
    with pytest.warns(UserWarning, match="writes geometry"):
        _point(variable="discharge", observes="NANCON", geometry=geometry)


def test_a_snap_reads_the_written_position_so_nothing_is_warned() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _point(variable="discharge", observes="NANCON", x=1.0, y=2.0, snap_radius="150 m")


def test_an_output_that_writes_only_observes_loads_silently() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _point(variable="discharge", observes="NANCON")


def _quantity(output: dict) -> str:
    cfg = CalibrationConfig.model_validate(
        {
            "outputs": {"gauge": {"support": "point", **output}},
            "objective_blocks": [{"name": "fit", "metric": "nse", "uses_outputs": ["gauge"]}],
        }
    )
    return objective_comparison_table(cfg)[0]["quantity"]


def test_a_discharge_station_reads_the_whole_catchment_series() -> None:
    assert _quantity({"variable": "discharge", "observes": "NANCON"}) == (
        "discharge, station NANCON (whole-catchment series)"
    )


def test_the_written_x_and_y_are_never_printed_as_where_the_value_comes_from() -> None:
    with pytest.warns(UserWarning):
        quantity = _quantity(
            {"variable": "discharge", "observes": "NANCON", "x": 389285.91, "y": 6816518.749}
        )

    assert quantity == "discharge, station NANCON (whole-catchment series)"
    assert "389285" not in quantity


def test_a_snapped_station_says_how_far_it_may_move() -> None:
    quantity = _quantity({"variable": "discharge", "observes": "NANCON", "snap_radius": "0.15 km"})

    assert (
        quantity == "discharge, station NANCON (the most drained cell within 150 m of its record)"
    )


def test_a_head_station_is_read_in_the_cell_its_record_falls_in() -> None:
    assert _quantity({"variable": "head", "observes": "PZ1"}) == (
        "head, station PZ1 (the cell its record falls in)"
    )


def test_a_point_without_a_station_still_prints_its_coordinates() -> None:
    assert _quantity({"variable": "head", "x": 10.0, "y": 20.0}) == "head (point, (10, 20))"
