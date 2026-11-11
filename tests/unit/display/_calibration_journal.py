"""A real session directory, written the way a calibration writes it.

The figures draw a :class:`~hydromodpy.results.session.view.Session`. The
session is written by
:class:`hydromodpy.calibration.persistence.CalibrationPersistence` under
``sessions/<name>/``, the trials by ``append_trial``, the frozen configuration
as ``config.toml`` and one descriptor per phase.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w

from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.core.state.result_dirs import session_dir_rel
from hydromodpy.results.session.descriptor import BestTrial, ParameterBound
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.session.phase import FrozenValue
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME
from tests._helpers.session_documents import trial_line

STARTED = datetime(2026, 9, 28, 12, 28, 25, tzinfo=UTC)


def _toml_ready(value: Any) -> Any:
    """Drop the ``None`` entries TOML cannot hold."""
    if isinstance(value, Mapping):
        return {key: _toml_ready(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_toml_ready(item) for item in value if item is not None]
    return value


def journal_session(
    project: Path,
    rows: list[dict[str, Any]],
    *,
    method: str = "bisection",
    phase: str = "search",
    config: dict[str, Any] | None = None,
    bounds: dict[str, ParameterBound] | None = None,
    best_trial: int | None = None,
    root_search: dict[str, Any] | None = None,
    name: str = "calibration",
    phases: Sequence[str] | None = None,
    phase_best: Mapping[str, int] | None = None,
    frozen: Mapping[str, Mapping[str, float]] | None = None,
    cost_name: str = "nse",
    named_phases: bool = True,
) -> Session:
    """Write one session under ``project`` and return it.

    A row is a journal row: ``trial`` (from 1, unique in the session),
    ``status``, ``cost``, ``parameters`` and ``components``. A row names its
    phase under ``phase``, else it belongs to ``phase``. ``phases`` lists the
    phases to open in order (default: the phase of the rows), ``phase_best``
    gives the best trial of each, ``frozen`` the values a phase carries from
    earlier ones. ``named_phases=False`` opens no phase directory, as a
    session that declared no phase.
    """
    persistence = CalibrationPersistence(project / session_dir_rel(name))
    persistence.directory.mkdir(parents=True, exist_ok=True)
    persistence.start_session(
        session_id=uuid.uuid4().hex,
        case_id=name,
        site=None,
        project="demo",
        config_hash="c0ffee",
        hydromodpy_version="2.0.0a5",
        method=method,
        cost_name=cost_name,
        bounds=bounds or {},
        windows={},
    )
    names = (
        list(phases)
        if phases is not None
        else list(dict.fromkeys(r.get("phase", phase) for r in rows))
    )
    if named_phases:
        for index, phase_name in enumerate(names):
            persistence.start_phase(
                PhaseContext(name=phase_name, index=index),
                frozen={
                    key: FrozenValue(value=value, mode="replace", from_phase=names[0])
                    for key, value in (frozen or {}).get(phase_name, {}).items()
                },
            )
    for row in rows:
        line = trial_line(
            int(row["trial"]),
            cost=row.get("cost"),
            case=name,
            phase=row.get("phase", phase),
            status="completed" if row.get("status", "completed") == "completed" else "failed",
            params=row["parameters"],
            components=row.get("components") or {},
            started_at=STARTED,
            ended_at=STARTED,
        )
        # The helper gives a trial with no parameter a default one.
        append_trial(
            persistence.directory,
            line if row["parameters"] else line.model_copy(update={"params": {}}),
        )
    if named_phases:
        for phase_name in names:
            held = (phase_best or {}).get(phase_name)
            persistence.finish_phase(
                phase_name,
                status="completed",
                best=None if held is None else BestTrial(trial=held),
            )
    persistence.finalize_session(
        status="completed",
        best=None if best_trial is None else BestTrial(trial=best_trial),
        root_search=root_search,
    )
    if config is not None:
        target = persistence.directory / SESSION_CONFIG_FILENAME
        target.write_text(tomli_w.dumps(_toml_ready({"calibration": config})), encoding="utf-8")
    return Session(persistence.directory)


# --------------------------------------------------------------------------- #
# the two searches example 04 runs on K
# --------------------------------------------------------------------------- #

NETWORK_CONFIG: dict[str, Any] = {
    "method": "bisection",
    "parameters": {"K": {"bounds": [1e-7, 1e-3], "search_space": "log", "units": "m/s"}},
    "outputs": {"seepage_network": {"support": "network"}},
    "objective_blocks": [
        {
            "name": "network_extension",
            "metric": "distance_gap",
            "weight": 1.0,
            "uses_outputs": ["seepage_network"],
            "normalize_cost": False,
            "search_space": "identity",
        }
    ],
    "uncertainty": {"method": "cost_profile", "cost_margin": None},
}

K_BOUNDS: dict[str, ParameterBound] = {
    "K": ParameterBound(lower=1e-7, upper=1e-3, search_space="log", units="m/s"),
}

STEADY_K: list[float] = [
    1e-07,
    4.6416e-07,
    2.1544e-06,
    1e-05,
    4.6416e-05,
    0.00021544,
    0.001,
    0.0001,
    6.8129e-05,
    8.254e-05,
    7.4989e-05,
    7.8674e-05,
    8.0584e-05,
    8.1556e-05,
    8.1069e-05,
]
"""The steady bisection on K of example 04, as its journal recorded it."""

STEADY_J: list[float] = [
    966.6,
    996.6,
    843.8,
    503.9,
    165.3,
    -270.1,
    -1467.9,
    -75.6,
    78.65,
    -3.186,
    12.10,
    7.553,
    2.730,
    -3.186,
    -1.965,
]
"""Its signed residual, D_so - D_os, in meters; the cost is its absolute value."""


def steady_bisection_rows() -> list[dict[str, Any]]:
    """One journal row per trial of the steady bisection, cost |J| in meters."""
    return [
        {
            "trial": trial,
            "status": "completed",
            "cost": abs(residual),
            "parameters": {
                "K": {"value": value, "bounds": [1e-7, 1e-3], "search_space": "log", "units": "m/s"}
            },
            "components": {
                "seepage_network.J_signed": residual,
                "seepage_network.D_so": 100.0 + max(residual, 0.0),
                "seepage_network.D_os": 100.0 + max(-residual, 0.0),
                "seepage_network.cell_spacing_m": 75.0,
                "seepage_network.h_obs": 75.0,
                "network_extension.raw_cost": abs(residual),
            },
        }
        for trial, (value, residual) in enumerate(zip(STEADY_K, STEADY_J, strict=True), start=1)
    ]


TWO_ROOT_K: list[float] = [
    1e-07,
    4.642e-07,
    2.154e-06,
    1e-05,
    4.642e-05,
    0.0002154,
    0.001,
    2.154e-05,
    3.162e-05,
    2.61e-05,
    2.371e-05,
    2.488e-05,
    2.548e-05,
    2.579e-05,
    2.564e-05,
    1e-06,
    1.468e-06,
    1.212e-06,
    1.334e-06,
    1.399e-06,
    1.366e-06,
    1.35e-06,
    1.358e-06,
    5.9e-06,
]
"""The transient bisection on two bounds of example 04, as its journal recorded it."""

TWO_ROOT_J: dict[str, list[float]] = {
    "minimal": [
        80.01,
        312.0,
        375.4,
        242.1,
        -137.2,
        -771.9,
        -2387.8,
        82.76,
        -21.32,
        -4.251,
        62.91,
        58.75,
        50.89,
        -4.251,
        -2.397,
        367.4,
        374.9,
        369.6,
        375.3,
        374.9,
        375.3,
        375.3,
        375.3,
        296.6,
    ],
    "maximal": [
        63.60,
        41.40,
        -23.88,
        -120.2,
        -371.7,
        -987.9,
        -3200.9,
        -212.1,
        -282.7,
        -226.6,
        -219.2,
        -222.9,
        -223.3,
        -223.0,
        -223.3,
        14.04,
        -3.349,
        4.471,
        0.2740,
        -1.334,
        -0.3032,
        0.1727,
        0.06005,
        -74.20,
    ],
}

TWO_ROOT_COST: list[float] = [
    71.80,
    176.7,
    199.7,
    181.2,
    254.4,
    879.9,
    2794.3,
    147.4,
    152.0,
    115.4,
    141.1,
    140.8,
    137.1,
    113.6,
    112.9,
    190.7,
    189.1,
    187.0,
    187.8,
    188.1,
    187.8,
    187.7,
    187.7,
    185.4,
]
"""Its cost, lowest at the first trial (K = 1e-7), far from the value it returned."""

TWO_ROOTS: dict[str, Any] = {
    "roots": {
        "parameter": "K",
        "minimal": {
            "k_star": 2.5636e-05,
            "trial_id": 15,
            "residual": -2.397,
            "weight": 0.5,
            "low": 2.5483e-05,
            "high": 2.5636e-05,
            "closed": True,
        },
        "maximal": {
            "k_star": 1.3577e-06,
            "trial_id": 23,
            "residual": 0.06005,
            "weight": 0.5,
            "low": 1.3577e-06,
            "high": 1.3659e-06,
            "closed": True,
        },
        "delta_log10": -1.276,
        "value": 5.8997e-06,
        "combined_trial_id": 24,
        "closed": True,
    }
}
"""The ``root_search`` record the journal kept for that search."""

TWO_ROOT_CONFIG: dict[str, Any] = {
    **NETWORK_CONFIG,
    "objective_blocks": [{**NETWORK_CONFIG["objective_blocks"][0], "name": "network_extent"}],
}


def two_root_rows() -> list[dict[str, Any]]:
    """One journal row per trial of the two-bound search: one residual per bound."""
    rows = []
    for index, value in enumerate(TWO_ROOT_K):
        components = {
            "seepage_network.n_bounds_scored": 2.0,
            "seepage_network.cell_spacing_m": 75.0,
            "network_extent.raw_cost": TWO_ROOT_COST[index],
        }
        for bound in ("minimal", "maximal"):
            components[f"seepage_network.J_signed_{bound}"] = TWO_ROOT_J[bound][index]
            components[f"seepage_network.weight_{bound}"] = 0.5
        rows.append(
            {
                "trial": index + 1,
                "status": "completed",
                "cost": TWO_ROOT_COST[index],
                "parameters": {
                    "K": {
                        "value": value,
                        "bounds": [1e-7, 1e-3],
                        "search_space": "log",
                        "units": "m/s",
                    }
                },
                "components": components,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# flat tables, for the figures that read nothing but the sampled values
# --------------------------------------------------------------------------- #

_NOT_PARAMETERS = frozenset({"trial", "iter", "objective", "cost", "status", "components"})


def flat_session(
    project: Path,
    columns: Mapping[str, Sequence[Any]],
    *,
    name: str = "calibration",
    components: Sequence[Mapping[str, float]] | None = None,
) -> Session:
    """Write a session from a flat table, one list per column.

    ``trial`` (from 1) numbers the rows, ``objective`` or ``cost`` is the cost
    (NaN for a failed trial), ``status`` is ``ok`` or anything else for a
    failure, and every other column is a sampled parameter.
    """
    size = len(next(iter(columns.values())))
    cost = columns.get("objective", columns.get("cost", [None] * size))
    rows = []
    for index in range(size):
        value = cost[index]
        failed = columns.get("status", ["ok"] * size)[index] not in ("ok", "completed")
        rows.append(
            {
                "trial": int(columns.get("trial", range(1, size + 1))[index]),
                "status": "failed" if failed else "completed",
                "cost": None if value is None or value != value else float(value),
                "parameters": {
                    key: float(values[index])
                    for key, values in columns.items()
                    if key not in _NOT_PARAMETERS
                },
                "components": {} if components is None else dict(components[index]),
            }
        )
    return journal_session(project, rows, name=name)
