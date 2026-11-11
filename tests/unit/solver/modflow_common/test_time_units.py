"""Every time unit a MODFLOW run can declare, in seconds.

MODFLOW 6 names its unit in the TDIS ``TIME_UNITS`` token and MODFLOW-NWT gives the DIS
``ITMUNI`` code, 1 to 5. A run that declares nothing runs in the launcher unit, seconds,
so a missing line never rescales a flux by 86 400. A code nothing knows is refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.time.window import SIMULATION_TIME_UNIT
from hydromodpy.solver.modflow_common.time_units import (
    declared_tdis_unit,
    factor_to_tracking_unit,
    read_itmuni_from_dis,
    read_time_units_from_tdis,
    resolve_solver_time_unit,
    seconds_per_itmuni,
    seconds_per_solver_time_unit,
    seconds_per_tdis_token,
)

# One row per ITMUNI code and TDIS token: the unit in seconds. A year is 365.25 days.
_UNITS = [
    pytest.param(1, "SECONDS", 1.0, id="seconds"),
    pytest.param(2, "MINUTES", 60.0, id="minutes"),
    pytest.param(3, "HOURS", 3600.0, id="hours"),
    pytest.param(4, "DAYS", 86400.0, id="days"),
    pytest.param(5, "YEARS", 31557600.0, id="years"),
]


@pytest.mark.parametrize(("itmuni", "_token", "seconds"), _UNITS)
def test_an_itmuni_code_is_a_number_of_seconds(itmuni, _token, seconds) -> None:
    assert seconds_per_itmuni(itmuni) == seconds


@pytest.mark.parametrize(("_itmuni", "token", "seconds"), _UNITS)
def test_a_tdis_token_is_a_number_of_seconds(tmp_path, _itmuni, token, seconds) -> None:
    (tmp_path / "case.tdis").write_text(f"BEGIN options\n  TIME_UNITS {token}\nEND options\n")

    assert read_time_units_from_tdis(tmp_path / "case.tdis") == token
    assert seconds_per_solver_time_unit(tmp_path, "case") == seconds


@pytest.mark.parametrize(("itmuni", "_token", "seconds"), _UNITS)
def test_a_dis_file_gives_its_unit_to_a_run_with_no_tdis(tmp_path, itmuni, _token, seconds) -> None:
    (tmp_path / "flow.dis").write_text(f"# header\n 1 2 3 4 {itmuni} 2\n 0\n")

    assert read_itmuni_from_dis(tmp_path / "flow.dis") == itmuni
    assert seconds_per_solver_time_unit(tmp_path, "flow") == seconds


def test_itmuni_zero_is_the_launcher_unit_and_not_days() -> None:
    assert seconds_per_itmuni(0) == 1.0
    assert SIMULATION_TIME_UNIT == "seconds"


@pytest.mark.parametrize("itmuni", [6, -1, 99])
def test_an_itmuni_code_nothing_knows_is_refused(itmuni) -> None:
    with pytest.raises(ValueError, match="Unsupported ITMUNI code"):
        seconds_per_itmuni(itmuni)


@pytest.mark.parametrize(("_itmuni", "token", "seconds"), _UNITS)
def test_a_tdis_token_alone_is_a_number_of_seconds(_itmuni, token, seconds) -> None:
    assert seconds_per_tdis_token(token) == seconds
    assert seconds_per_tdis_token(f" {token.lower()} ") == seconds


# One row per token that declares no unit: it is the launcher unit, never days.
_UNDECLARED_TOKENS = [
    pytest.param("UNKNOWN", id="unknown"),
    pytest.param("unknown", id="unknown_lower_case"),
    pytest.param("", id="empty"),
    pytest.param("  ", id="blank"),
]


@pytest.mark.parametrize("token", _UNDECLARED_TOKENS)
def test_an_undeclared_tdis_token_is_the_launcher_unit(token) -> None:
    assert declared_tdis_unit(token) is None
    assert seconds_per_tdis_token(token) == 1.0


@pytest.mark.parametrize("token", ["FORTNIGHTS", "DAYZ"])
def test_a_tdis_token_that_is_no_unit_is_refused(token) -> None:
    with pytest.raises(ValueError):
        seconds_per_tdis_token(token)


# One row per declaration a run can leave: its files, and the unit the run resolves to.
_DECLARATIONS = [
    pytest.param({}, SIMULATION_TIME_UNIT, id="nothing_declared"),
    pytest.param({"case.tdis": "TIME_UNITS UNKNOWN\n"}, SIMULATION_TIME_UNIT, id="unknown_token"),
    pytest.param({"case.dis": " 1 1 1 1 0 2\n"}, SIMULATION_TIME_UNIT, id="itmuni_zero"),
    pytest.param({"case.dis": " 1 1 1\n"}, SIMULATION_TIME_UNIT, id="short_dis_record"),
    pytest.param(
        {"case.tdis": "TIME_UNITS DAYS\n", "case.dis": " 1 1 1 1 3 2\n"}, "days", id="tdis_wins"
    ),
]


@pytest.mark.parametrize(("files", "unit"), _DECLARATIONS)
def test_a_run_resolves_the_unit_it_declares_or_the_launcher_unit(tmp_path, files, unit) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)

    assert resolve_solver_time_unit(tmp_path, "case") == unit


def test_a_declared_token_that_is_no_unit_is_corrupt_and_refused(tmp_path: Path) -> None:
    (tmp_path / "case.tdis").write_text("TIME_UNITS FORTNIGHTS\n")

    with pytest.raises(ValueError, match="Unsupported time unit"):
        resolve_solver_time_unit(tmp_path, "case")


def test_a_tracking_time_is_one_model_unit_in_days() -> None:
    assert factor_to_tracking_unit("days") == 1.0
    assert factor_to_tracking_unit("seconds") == pytest.approx(1.0 / 86400.0)
    assert factor_to_tracking_unit("years") == pytest.approx(365.25)
