"""Trial cache of a calibration (`optim.cache`).
A trial is looked up by a key built from its parameters and from the context
that changes its cost (outputs, map files, mesh, scoring rule). Costs are
dimensionless.
"""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import ParamsHashCache, _normalize_context, params_hash
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import state
from hydromodpy.calibration.runners.staged_runner import _phase_config
from hydromodpy.calibration.runners.state import mesh_fingerprint, preload_hash_cache
from hydromodpy.results.session.journal import trials_path
from tests.unit.calibration._factories import unit_space
from tests.unit.calibration._factories_search import result_of, run_engine

BASE: dict[str, Any] = {
    "method": "scipy_nelder_mead",
    "max_trials": 5,
    "precision": 0.01,
    "seed": 3,
    "method_options": {"fatol": 1e-4},
    "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
}
NETWORK_PARAMETERS = {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}

# Mesh centroids (m) of two 2 x 2 meshes, one with 10 m cells and one with 5 m cells.
CENTERS_10_M = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]])
CENTERS_5_M = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 5.0], [5.0, 5.0]])


def network_config(**paths: Path) -> CalibrationConfig:
    output: dict[str, Any] = {
        "support": "network",
        "map": {key: str(value) for key, value in paths.items()},
    }
    if "permanent" in paths:
        output["map"]["calibrate_on"] = "permanent"
    return CalibrationConfig.model_validate(
        {
            "parameters": NETWORK_PARAMETERS,
            "outputs": {"net": output},
            "objective_blocks": [
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def cache_context(cfg: CalibrationConfig) -> dict[str, object]:
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


def network_key(cfg: CalibrationConfig) -> str:
    return params_hash({"K": 1e-5}, context=cache_context(cfg))


def base_key(**changes: Any) -> str:
    cfg = CalibrationConfig.model_validate({**BASE, **changes})
    return params_hash({"k": 1e-4}, context=cache_context(cfg))


def journal_session(
    project_root: Path, name: str, hash_value: str, components: dict[str, float] | None = None
) -> Path:
    """Write a one-trial session whose journal carries `hash_value`."""
    session_dir = project_root / "sessions" / name
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id=name,
        site=None,
        project="p",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        cost_name="rmse",
        bounds={},
        windows={},
    )
    persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"K": 1.0}),
        EvaluationResult(
            trial_id=1,
            sim_id=None,
            cost=0.5,
            status="completed",
            components={"J": 0.5} if components is None else components,
            metadata={"params_hash": hash_value},
        ),
    )
    return session_dir


def mesh_context(centers: np.ndarray) -> SimpleNamespace:
    mesh = SimpleNamespace(centers=centers, structured_shape=(2, 2))
    return SimpleNamespace(setup=SimpleNamespace(cell_mesh=mesh, mesh_summary=None))


def evaluate_x(sugg: ParamSuggestion) -> EvaluationResult:
    # The cost is x, and the sim id encodes the trial id.
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=f"sim-{sugg.trial_id}",
        cost=float(sugg.values["x"]),
        status="completed",
    )


def warning_of_exhausted_search(caplog) -> str:
    space = ParameterSpace(
        [
            CalibParameter(name="x", lower=-1.0, upper=1.0),
            CalibParameter(name="y", lower=-1.0, upper=1.0),
        ]
    )
    optimizer = build_optimizer("scipy_nelder_mead", space, seed=1, xatol=0.0, fatol=0.0)
    rng = np.random.default_rng(5)

    with caplog.at_level(logging.WARNING):
        run_engine(space, optimizer, lambda s: result_of(s, float(rng.uniform(1.0, 2.0))), 12)
    (record,) = [r for r in caplog.records if "did NOT converge" in r.getMessage()]
    return record.getMessage()


NORMALIZED = [
    pytest.param(float("inf"), float("inf"), id="infinity"),
    pytest.param(0.0, 0.0, id="zero"),
    pytest.param(1.23456, 1.23, id="rounded"),
    pytest.param({"b": Path("/data/a.tif"), "a": 1.0}, {"a": 1.0, "b": "/data/a.tif"}, id="dict"),
    pytest.param({3.0, 1.0, 2.0}, [1.0, 2.0, 3.0], id="set"),
    pytest.param((1.0, [0.5]), [1.0, [0.5]], id="tuple"),
]


@pytest.mark.parametrize(("value", "expected"), NORMALIZED)
def test_context_value_normalized(value, expected):
    assert _normalize_context(value, precision=3) == expected


def test_hash_ignores_key_order():
    assert params_hash({"a": 0.1, "b": 0.2}) == params_hash({"b": 0.2, "a": 0.1})


def test_hash_is_sha256_hex():
    digest = params_hash({"a": 1.0})

    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_same_map_same_key(tmp_path):
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")

    assert network_key(network_config(complete=streams)) == network_key(
        network_config(complete=streams)
    )


@pytest.mark.parametrize("field", ["complete", "permanent"])
def test_rewritten_map_moves_key(tmp_path, field):
    paths = {"complete": tmp_path / "streams.gpkg"}
    if field == "permanent":
        paths[field] = tmp_path / "permanent.gpkg"
    target = paths[field]
    paths["complete"].write_bytes(b"reaches v1")
    target.write_bytes(b"reaches v1")
    before = network_key(network_config(**paths))

    target.write_bytes(b"reaches v2")

    assert network_key(network_config(**paths)) != before


def test_shapefile_attributes_move_key(tmp_path):
    streams = tmp_path / "streams.shp"
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        streams.with_suffix(suffix).write_bytes(b"part" + suffix.encode())
    before = network_key(network_config(complete=streams))

    streams.with_suffix(".dbf").write_bytes(b"other attributes")

    assert network_key(network_config(complete=streams)) != before


def test_validation_window_keys_the_cache():
    span = {"start": "2001-01-01", "end": "2001-12-31"}
    steady = {"name": "s", "parameters": ["k"], "objective": "nse", "regime": "steady"}
    phases = [
        {**steady, "steady_window": span},
        {**steady, "name": "t", "regime": None, "window": span},
    ]
    windows = [
        {},
        {"validation_window": {"start": "2002-01-01", "end": "2002-12-31"}},
        {"validation_window": {"start": "2003-01-01", "end": "2003-12-31"}},
    ]
    plain, late, later = (
        CalibrationConfig.model_validate({**BASE, "objective": "nse", "phases": phases, **fields})
        for fields in windows
    )
    keys = [
        [cache_context(_phase_config(cfg, phase)) for phase in cfg.phases]
        for cfg in (plain, late, later)
    ]

    # The steady phase never scores the window, the transient one does.
    assert keys[0][0] == keys[1][0] == keys[2][0]
    assert _phase_config(late, late.phases[0]).validation_window is None
    assert keys[0][1] != keys[1][1] != keys[2][1]
    assert "validation_window" not in str(keys[0][1])


def test_journal_unreadable_is_skipped(tmp_path, caplog):
    journal_session(tmp_path, "today", "v2:readable")
    alpha = journal_session(tmp_path, "alpha", "v2:alpha")
    line = json.loads(trials_path(alpha).read_text(encoding="utf-8").splitlines()[0])
    line["schema"] = "hydromodpy.trial.v0"
    trials_path(alpha).write_text(json.dumps(line) + "\n", encoding="utf-8")
    cache = ParamsHashCache()

    with caplog.at_level(logging.WARNING):
        added = preload_hash_cache(tmp_path, cache)

    assert added == 1
    assert "v2:readable" in cache
    assert "v2:alpha" not in cache
    assert "alpha" in caplog.text
    assert "solved again" in caplog.text


def test_trial_without_components_not_cached(tmp_path):
    journal_session(tmp_path, "bare", "v2:bare", components={})
    cache = ParamsHashCache()

    assert preload_hash_cache(tmp_path, cache) == 0
    assert "v2:bare" not in cache


def test_meshes_fingerprint():
    ten = mesh_fingerprint(mesh_context(CENTERS_10_M))
    same = mesh_fingerprint(mesh_context(CENTERS_10_M.copy()))
    five = mesh_fingerprint(mesh_context(CENTERS_5_M))

    assert ten == same
    assert ten != five


def test_context_carries_mesh_fingerprint():
    assert "mesh_fingerprint" in inspect.getsource(state.build_cache_context)


def test_budget_caps_trials():
    space = unit_space()
    session = run_engine(space, build_optimizer("random_search", space, seed=0), evaluate_x, 4)

    assert len(session.history) == 4


def test_session_best_is_lowest_cost():
    space = unit_space()
    optimizer = build_optimizer("grid", space, points_per_dim=5)
    session = run_engine(space, optimizer, evaluate_x, 100)

    # The grid spans 0 to 1 with 5 points.
    assert session.best.cost == pytest.approx(0.0)


def test_larger_budget_replays(caplog):
    assert base_key(max_trials=500) == base_key()

    message = warning_of_exhausted_search(caplog)
    assert "Raise max_trials" in message
    assert "replays the trials already solved" in message


OUTSIDE_THE_KEY = [
    pytest.param("precision", {"precision": 0.1}, id="precision"),
    pytest.param("seed", {"seed": 4}, id="seed"),
    pytest.param("method_options", {"method_options": {"fatol": 1e-3}}, id="method options"),
    pytest.param(
        "method",
        {"method": "random_search", "precision": None, "method_options": {}},
        id="method",
    ),
]


@pytest.mark.parametrize(("name", "change"), OUTSIDE_THE_KEY)
def test_warning_names_what_the_key_ignores(name, change, caplog):
    assert base_key(**change) == base_key()

    message = warning_of_exhausted_search(caplog)
    assert name in message
    sentence = next(s for s in message.split(".") if name in s)
    assert "values already solved" in sentence
    assert "cache key" not in sentence
