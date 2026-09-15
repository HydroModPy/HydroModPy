"""Read back the time unit a MODFLOW run declared in its own input files.

Both backends write the unit they were built with: MODFLOW 6 as the TDIS
``TIME_UNITS`` token, MODFLOW-NWT as the DIS ``ITMUNI`` code. Extractors read it
from disk rather than from the in-memory model because they also run detached
from the build that produced the run.

When a run declares nothing readable, the unit is
:data:`~hydromodpy.core.time.SIMULATION_TIME_UNIT`. The launcher builds every
run in that unit, so falling back to days instead would rescale fluxes and
travel times by 86400 without a single error. A declaration that is present but
not a MODFLOW unit raises instead: the run wrote that file itself, so the value
is corrupt rather than merely absent.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.time import SIMULATION_TIME_UNIT
from hydromodpy.core.units import factor_to_seconds, normalize_time_unit

# MODFLOW 6 accepts UNKNOWN to mean "no declared unit", and MODFLOW spells the
# same thing as ITMUNI 0. Both land on the launcher unit.
_UNDECLARED_TOKENS = ("", "UNKNOWN")

# Particle tracking clocks are the one product stored in days rather than in the
# SI seconds of the simulation time axis: a residence time is read in days and
# years. Both extractors declare it on the ``particles`` group, so a reader
# never has to assume which of the two units it got.
TRACKING_TIME_UNIT = "days"


def read_time_units_from_tdis(tdis_path: Path) -> str | None:
    """Return the MODFLOW 6 TDIS ``TIME_UNITS`` token, or None when unreadable."""
    tdis_path = Path(tdis_path)
    if not tdis_path.is_file():
        return None
    try:
        with tdis_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                tokens = raw.strip().split()
                if len(tokens) >= 2 and tokens[0].upper() == "TIME_UNITS":
                    return tokens[1].upper()
    except OSError:
        return None
    return None


def read_itmuni_from_dis(dis_path: Path) -> int | None:
    """Return the ``ITMUNI`` code of a MODFLOW DIS file, or None when unreadable.

    The first non-comment record is ``NLAY NROW NCOL NPER ITMUNI LENUNI``, so
    ITMUNI is its fifth token. The line after it is LAYCBD, not a second
    header.
    """
    dis_path = Path(dis_path)
    if not dis_path.is_file():
        return None
    try:
        with dis_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                tokens = stripped.split()
                if len(tokens) < 5:
                    return None
                return int(tokens[4])
    except (OSError, ValueError):
        return None
    return None


def resolve_solver_time_unit(solver_output_dir: Path, model_name: str) -> str:
    """Canonical time unit of one run, read from its own TDIS or DIS file.

    The TDIS file name may differ from the model name, so glob for it before
    giving up and trying the MODFLOW-NWT DIS.
    """
    solver_output_dir = Path(solver_output_dir)
    tdis_path = solver_output_dir / f"{model_name}.tdis"
    if not tdis_path.is_file():
        tdis_path = next(iter(solver_output_dir.glob("*.tdis")), tdis_path)

    token = read_time_units_from_tdis(tdis_path)
    if token is not None and token not in _UNDECLARED_TOKENS:
        return normalize_time_unit(token)

    itmuni = read_itmuni_from_dis(solver_output_dir / f"{model_name}.dis")
    if itmuni is not None and itmuni != 0:
        return normalize_time_unit(itmuni)

    return SIMULATION_TIME_UNIT


def seconds_per_itmuni(itmuni: int) -> float:
    """Seconds per MODFLOW ITMUNI code; 0 means undeclared, so the launcher unit."""
    if itmuni == 0:
        return factor_to_seconds(SIMULATION_TIME_UNIT)
    return factor_to_seconds(normalize_time_unit(int(itmuni)))


def seconds_per_solver_time_unit(solver_output_dir: Path, model_name: str) -> float:
    """Seconds per native time unit of one run, to convert its outputs to SI."""
    return factor_to_seconds(resolve_solver_time_unit(solver_output_dir, model_name))


def factor_to_tracking_unit(time_units: str) -> float:
    """Return the factor converting one model time unit to the tracking unit."""
    return factor_to_seconds(time_units) / factor_to_seconds(TRACKING_TIME_UNIT)
