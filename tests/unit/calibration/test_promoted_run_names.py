"""A promoted run is named after the file's simulation and the phase it closes.

Three calibration files of one project used to promote ``bisection_iter_0015``,
``bisection_iter_0015.v2`` and ``bisection_iter_0015.v3``: a reader could not
tell which file produced which run. The name now carries the ``[simulation]``
name, which differs from one file to the next, and the phase.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners.promotion import (
    promote_iterations,
    promoted_run_name,
    registered_run_name,
)
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.catalog import Catalog


def _trial_ctx(name: str | None, cfg_path: str = "/x/run_calibration.toml") -> SimpleNamespace:
    return SimpleNamespace(
        base_cfg=SimpleNamespace(simulation=SimpleNamespace(name=name)),
        cfg_path=Path(cfg_path),
    )


def test_a_phase_of_a_staged_calibration_carries_its_name() -> None:
    ctx = _trial_ctx("nancon_calibrated")

    assert promoted_run_name(ctx, "steady_conductivity") == "nancon_calibrated_steady_conductivity"


def test_a_one_phase_calibration_takes_the_simulation_name() -> None:
    assert promoted_run_name(_trial_ctx("nancon_calibrated"), None) == "nancon_calibrated"


def test_two_files_of_one_project_promote_two_names() -> None:
    by_protocol = promoted_run_name(_trial_ctx("nancon_calibrated"), "transient_storage")
    by_hand = promoted_run_name(_trial_ctx("nancon_by_hand"), "transient_storage")

    assert by_protocol != by_hand


def test_a_file_without_a_simulation_name_falls_back_to_its_stem() -> None:
    assert promoted_run_name(_trial_ctx(None), "steady") == "run_calibration_steady"


def test_a_name_too_long_for_a_run_folder_is_refused_before_the_search() -> None:
    with pytest.raises(CalibrationError, match="Shorten the"):
        promoted_run_name(_trial_ctx("n" * 70), "transient_storage_of_the_aquifer")


class _Persistence:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def top_n(self, session_id: str, n: int) -> list[dict[str, Any]]:
        del session_id
        return self._rows[:n]

    def load_iterations(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        return list(self._rows)


def _cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "max_iter": 3,
            "save_runs": "best_n",
            "save_best_n": 2,
            "objective": "nse",
            "variable": "discharge",
            "use_cache": False,
            "parameters": {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "transform": "log",
                    "prior": "log_uniform",
                    "path": "flow.param.K.field.value",
                }
            },
        }
    )


def test_the_best_trial_takes_the_name_and_a_kept_one_its_trial_number(
    tmp_path, monkeypatch
) -> None:
    rows = [
        {"iteration": 7, "parameters": {"K": 1e-4}, "objective_value": 0.1, "status": "completed"},
        {"iteration": 3, "parameters": {"K": 1e-5}, "objective_value": 0.2, "status": "completed"},
    ]
    names: list[str] = []

    def _fake(
        trial_ctx,
        values,
        *,
        name=None,
        tags=(),
        session_id=None,
        sim_id=None,
        kept=None,
        spared=(),
    ):
        del trial_ctx, values, tags, session_id, kept, spared
        names.append(str(name))
        return sim_id

    monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fake)
    monkeypatch.setattr(promotion_module, "update_iter_sim_id", lambda *args: None)
    best = EvaluationResult(trial_id=7, sim_id=None, objective_value=0.1, status="completed")

    count, failures, best_sim_id = promote_iterations(
        cfg=_cfg(),
        trial_ctx=SimpleNamespace(kept_solves=None),
        catalog=None,
        persistence=_Persistence(rows),
        session_id=uuid.uuid4().hex,
        best=best,
        override_paths={"K": "flow.param.K.field.value"},
        run_name="nancon_steady",
    )

    assert (count, failures) == (2, [])
    assert best_sim_id is not None
    assert names == ["nancon_steady", "nancon_steady_trial_0003"]


def test_the_registered_name_is_read_back_from_the_index(tmp_path) -> None:
    sim_id = str(uuid.uuid4())
    with Catalog(tmp_path) as catalog:
        solver = catalog.connection.execute("SELECT MIN(id) FROM solvers").fetchone()[0]
        catalog.connection.execute(
            "INSERT INTO simulations (sim_id, name, project, solver_id, zarr_path, "
            "storage_basename) VALUES (?, ?, ?, ?, ?, ?)",
            [uuid.UUID(sim_id), "nancon_steady.v2", "p", solver, "f.zarr", "nancon_steady.v2"],
        )

        assert registered_run_name(catalog, sim_id) == "nancon_steady.v2"
        assert registered_run_name(catalog, None) is None
        assert registered_run_name(catalog, str(uuid.uuid4())) is None
