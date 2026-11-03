"""A run-shaped carrier whose session lives in a real session directory on disk.

The rows of ``calibration_sessions`` carry one phase each; ``session.json``
keeps the best trial, the root search record and the bounds of the
session. A figure drawn from a promoted run reads them from the session
directory the run was promoted from, found from the directory of the run.
The carrier here is built the same way: the session is written by
:class:`hydromodpy.calibration.persistence.CalibrationPersistence` under
``sessions/<name>/``, and the carrier sits at ``runs/<name>`` of the same
project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.core.state.paths import run_dir_rel, session_dir_rel
from hydromodpy.results.session.descriptor import BestTrial, ParameterBound

STARTED = datetime(2026, 9, 28, 12, 28, 25, tzinfo=UTC)


def journal_run(
    project: Path,
    rows: list[dict[str, Any]],
    *,
    method: str,
    phase: str,
    config: dict[str, Any],
    bounds: dict[str, ParameterBound],
    best_trial: int | None,
    root_search: dict[str, Any] | None = None,
    name: str = "calibration",
) -> SimpleNamespace:
    """Write one session directory under ``project`` and return a run carrying its trials."""
    session_id = uuid.uuid4().hex
    persistence = CalibrationPersistence(project / session_dir_rel(name))
    persistence.directory.mkdir(parents=True, exist_ok=True)
    persistence.start_session(
        session_id=session_id,
        case_id=name,
        site=None,
        project="demo",
        config_hash="c0ffee",
        hydromodpy_version="2.0.0a5",
        method=method,
        cost_name="nse",
        bounds=bounds,
        windows={},
    )
    persistence.finalize_session(
        status="completed",
        best=None if best_trial is None else BestTrial(trial=best_trial),
        root_search=root_search,
    )
    # One row per phase: the session as a whole lives in session.json.
    session_row = {
        "session_id": session_id,
        "method": method,
        "phase_name": phase,
        "phase_index": 0,
        "started_at": STARTED.isoformat(),
        "config": config,
    }
    trials = [{**row, "session_id": session_id} for row in rows]
    return SimpleNamespace(
        sim_id="sim-demo",
        name=name,
        dir=project / run_dir_rel(name),
        calibration_iterations=pd.DataFrame(trials),
        calibration_sessions=pd.DataFrame([session_row]),
        has_table=lambda table: table == "calibration_iterations",
        has_field=lambda field: False,
    )


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
"""Its signed residual, D_so - D_os, in metres; the cost is its absolute value."""


def steady_bisection_rows() -> list[dict[str, Any]]:
    """One journal row per trial of the steady bisection, cost |J| in metres."""
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
