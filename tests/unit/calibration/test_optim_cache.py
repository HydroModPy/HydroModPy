"""Tests of `optim.cache`."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Mapping
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
from hydromodpy.calibration.runners.state import (
    build_cache_context,
    mesh_fingerprint,
    override_paths,
    preload_hash_cache,
    space_from_config,
)
from hydromodpy.results.session.journal import trials_path
from tests.unit.calibration._factories import unit_space
from tests.unit.calibration._factories_search import result_of, run_engine

# From test_a_map_rewritten_in_place_moves_the_cache_key.py
# A map rewritten at the same path moves the cache key of a network calibration.
#
# The key held the path of ``map.complete`` and of
# ``map.permanent``, never what the file holds. A map redrawn and
# saved under the same name scored nothing new: every trial came back from the
# cache with the cost of the old map. The key now holds the content of each map
# file, with the sidecars of a shapefile, and only a document that names a map
# carries it.


PARAMETERS = {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}


def _network(**paths: Path) -> CalibrationConfig:
    output: dict[str, Any] = {
        "support": "network",
        "map": {key: str(value) for key, value in paths.items()},
    }
    if "permanent" in paths:
        output["map"]["calibrate_on"] = "permanent"
    return CalibrationConfig.model_validate(
        {
            "parameters": PARAMETERS,
            "outputs": {"net": output},
            "objective_blocks": [
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def _context(cfg: CalibrationConfig) -> dict[str, object]:
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


def _key(cfg: CalibrationConfig) -> str:
    return params_hash({"K": 1e-5}, context=_context(cfg))


def test_the_same_map_keeps_its_key(tmp_path: Path) -> None:
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")

    assert _key(_network(complete=streams)) == _key(_network(complete=streams))


@pytest.mark.parametrize("field", ["complete", "permanent"])
def test_a_map_rewritten_at_its_path_moves_the_key(tmp_path: Path, field: str) -> None:
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")
    paths = {"complete": streams}
    if field == "permanent":
        paths[field] = tmp_path / "permanent.gpkg"
    target = paths[field]
    target.write_bytes(b"reaches v1")
    before = _key(_network(**paths))

    target.write_bytes(b"reaches v2")

    assert _key(_network(**paths)) != before


def test_the_attributes_of_a_shapefile_move_the_key(tmp_path: Path) -> None:
    streams = tmp_path / "streams.shp"
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        streams.with_suffix(suffix).write_bytes(b"part" + suffix.encode())
    before = _key(_network(complete=streams))

    streams.with_suffix(".dbf").write_bytes(b"other attributes")

    assert _key(_network(complete=streams)) != before


# From test_an_unreadable_journal_does_not_stop_the_cache.py
# A journal this version cannot read is skipped by the trial cache, with a warning.
#
# Every search preloads its cache from the ``trials.jsonl`` of all the sessions
# of the project. A session written before a schema change is refused by the
# journal reader, and the preload used to let that refusal stop the new
# calibration, after its own session had opened. Its points are now solved again.


def _session(
    project_root: Path, name: str, params_hash: str, components: dict[str, float] | None = None
) -> Path:
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
            metadata={"params_hash": params_hash},
        ),
    )
    return session_dir


def test_the_cache_skips_an_unreadable_journal_and_keeps_the_others(tmp_path, caplog) -> None:
    _session(tmp_path, "today", "v2:readable")
    alpha = _session(tmp_path, "alpha", "v2:alpha")
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


def test_a_trial_that_kept_no_components_is_solved_again(tmp_path) -> None:
    _session(tmp_path, "bare", "v2:bare", components={})
    cache = ParamsHashCache()

    assert preload_hash_cache(tmp_path, cache) == 0
    assert "v2:bare" not in cache


# From test_calibration_cache.py
# Unit tests for hydromodpy.calibration.optim.cache (params_hash + cache).


class TestContextNormalisation:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (float("inf"), float("inf")),
            (0.0, 0.0),
            (1.23456, 1.23),
            ({"b": Path("/data/a.tif"), "a": 1.0}, {"a": 1.0, "b": "/data/a.tif"}),
            ({3.0, 1.0, 2.0}, [1.0, 2.0, 3.0]),
            ((1.0, [0.5]), [1.0, [0.5]]),
        ],
    )
    def test_a_context_value_is_rounded_ordered_and_made_plain(self, value, expected) -> None:
        assert _normalize_context(value, precision=3) == expected


class TestParamsHash:
    def test_stable_across_orderings(self):
        h1 = params_hash({"a": 0.1, "b": 0.2})
        h2 = params_hash({"b": 0.2, "a": 0.1})
        assert h1 == h2

    def test_hex_string_length(self):
        h = params_hash({"a": 1.0})
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


# From test_engine.py
# Unit tests for ``hydromodpy.calibration.optim.engine``.
#
# Ports the behavioral intent of the old ``test_calibration2_core.py``
# to the new ask/tell architecture. The old engine took raw ``observed``
# arrays and bounds dicts and dispatched a named method; the new engine
# is solver-agnostic and takes ``space`` + ``optimizer`` + ``evaluator``.
# Tests below cover the equivalent ground:
#
# - history accumulation and ``session.best`` exposure,
# - interaction with :class:`ParamsHashCache`,
# - the ``on_iteration`` callback hook,
# - graceful termination when the optimizer runs out of suggestions,
# - edge cases ``max_trials=0`` and ``batch_size > max_trials``.


def _simple_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
    """Deterministic evaluator: objective = x, sim_id encodes trial_id."""
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=f"sim-{sugg.trial_id}",
        cost=float(sugg.values["x"]),
        status="completed",
    )


class _StubOptimizer:
    """Minimal ask/tell optimizer used to drive controlled scenarios.

    Implements the Protocol explicitly so we don't depend on how the
    built-in adapters happen to behave. ``suggestions`` is a list of
    parameter dicts served one at a time (per ``ask`` call).
    """

    name = "stub"

    def __init__(self, suggestions: list[Mapping[str, float]]):
        self._suggestions = list(suggestions)
        self._trial_id = 0
        self._history: list[EvaluationResult] = []
        self._exhausted = False

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            if not self._suggestions:
                self._exhausted = True
                break
            values = self._suggestions.pop(0)
            self._trial_id += 1
            out.append(ParamSuggestion(trial_id=self._trial_id, values=dict(values)))
        return out

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("stub exhausted")
        return got[0]

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.cost)

    def converged(self) -> bool:
        return self._exhausted


# ---------------------------------------------------------------------------
# Engine orchestration
# ---------------------------------------------------------------------------
class TestEngineRun:
    def test_respects_max_trials_when_budget_is_binding(self):
        """``max_trials`` caps iterations even if the optimizer has more points."""
        space = unit_space()
        opt = build_optimizer("random_search", space, seed=0)
        session = run_engine(space, opt, _simple_evaluator, 4)
        assert len(session.history) == 4

    def test_session_best_returns_lowest_objective(self):
        """``session.best`` must surface the best completed trial."""
        space = unit_space()
        opt = build_optimizer("grid", space, points_per_dim=5)
        session = run_engine(space, opt, _simple_evaluator, 100)
        assert session.best is not None
        # Grid spans [0.0, 1.0] with 5 points - min is 0.0.
        assert session.best.cost == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# on_iteration callback
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ParamsHashCache integration
# ---------------------------------------------------------------------------


# From test_the_cache_key_holds_only_what_changes_a_cost.py
# The cache key is a whitelist: what changes the cost of a trial at given parameters.
#
# The key was the whole ``[calibration]`` table minus a list of runtime keys, so a
# new key of the section moved it silently and a change of method, seed, precision
# or option re-solved trials whose cost had not changed. Now the same parameter
# values hash to one key under two methods, seeds, precisions, budgets, option sets
# and phase bounds, and to another under another output, block, window or
# evaluator.


OUTPUT = {"support": "point", "variable": "head", "observes": "P1"}
BASE: dict[str, Any] = {
    "method": "scipy_nelder_mead",
    "max_trials": 5,
    "precision": 0.01,
    "seed": 3,
    "method_options": {"fatol": 1e-4},
    "parameters": {
        "k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2], "search_space": "log"}
    },
    "objective": "nse",
    "variable": "discharge",
}


def _hash(**changes: Any) -> str:
    payload = {**BASE, **changes}
    if "objective_blocks" in changes:
        del payload["objective"]  # blocks score by their own metric
    cfg = CalibrationConfig.model_validate(payload)
    return params_hash({"k": 1e-4}, context=_context(cfg))


def test_a_validation_window_keys_the_cache_of_a_search_it_scores_once_written() -> None:
    span = {"start": "2001-01-01", "end": "2001-12-31"}
    steady = {"name": "s", "parameters": ["k"], "objective": "nse", "regime": "steady"}
    phases = [
        {**steady, "steady_window": span},
        {**steady, "name": "t", "regime": None, "window": span},
    ]
    plain, late, later = (
        CalibrationConfig.model_validate(
            {**BASE, "phases": phases, **fields},
        )
        for fields in (
            {},
            {"validation_window": {"start": "2002-01-01", "end": "2002-12-31"}},
            {"validation_window": {"start": "2003-01-01", "end": "2003-12-31"}},
        )
    )
    keys = [
        [_context(_phase_config(cfg, phase)) for phase in cfg.phases]
        for cfg in (plain, late, later)
    ]

    assert keys[0][0] == keys[1][0] == keys[2][0]
    assert _phase_config(late, late.phases[0]).validation_window is None
    assert keys[0][1] != keys[1][1] != keys[2][1]
    assert "validation_window" not in str(keys[0][1])


# From test_the_cache_key_holds_the_mesh.py
# A cached cost must belong to the mesh it was computed on.
#
# The evaluation cache is keyed on the parameters plus a context describing the
# model. That context deliberately dropped ``mesh_catchment``, so two runs whose
# only difference was the mesh shared their cache entries: the second one served
# the first one's objectives without re-solving, on a different discretization.
#
# Declaring the requested mesh settings would not be enough either. gmsh is not
# reproducible: the same request can produce a different triangulation, and the
# stream-network criterion is normalized by cell size, so a cost from another mesh
# is not the same number. The fingerprint therefore describes the mesh that was
# BUILT, not the one that was asked for.


class _Mesh:
    def __init__(self, centroids: np.ndarray, *, structured: bool = True) -> None:
        self.centers = centroids
        self.structured_shape = (2, 2) if structured else None


def _ctx(mesh: object | None) -> SimpleNamespace:
    return SimpleNamespace(setup=SimpleNamespace(cell_mesh=mesh, mesh_summary=None))


_A = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]], dtype=float)
_B = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 5.0], [5.0, 5.0]], dtype=float)


class TestItDescribesTheMeshThatWasBuilt:
    def test_two_different_meshes_do_not_share_a_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_B)))

        assert first != second

    def test_the_same_mesh_yields_the_same_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_A.copy())))

        assert first == second


class TestItReachesTheCacheKey:
    def test_the_context_carries_it(self) -> None:
        source = inspect.getsource(state.build_cache_context)

        assert "mesh_fingerprint" in source


# From test_the_cache_key_names_the_score_rule.py
# A cost cached under another scoring rule is not served again.
#
# The session now reads its window as the run does (decision m01): a pair
# counts when its whole period lies in the window, not when its end stamp does.
# The same parameters therefore score on other periods than before, and a cost
# cached under the old reading must not be replayed. The cache key carries the
# version of the scoring rule, so the next bump of the rule re-solves too.


_DECLARED = {
    "method": "scipy_nelder_mead",
    "max_trials": 5,
    "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
}


def _context__cache_key_names() -> dict[str, object]:
    cfg = CalibrationConfig.model_validate(_DECLARED)
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


# From test_the_not_converged_warning_promises_only_what_the_cache_replays.py
# The "did NOT converge" warning names only what a re-run really replays.
#
# The cache key holds only what changes the cost of a trial at given parameter
# values. ``max_trials``, ``precision``, ``seed``, ``method`` and
# ``method_options`` are outside it, so a re-run that changes one replays the
# trials it proposes at values already solved. The message used to promise a
# replay after "loosening the precision" and, later, to say the key changed.


_DECLARED__not_converged = {
    "method": "scipy_nelder_mead",
    "max_trials": 5,
    "precision": 0.01,
    "seed": 3,
    "method_options": {"fatol": 1e-4},
    "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
}


def _hash__not_converged(**changes: object) -> str:
    cfg = CalibrationConfig.model_validate({**_DECLARED__not_converged, **changes})
    context = build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=space_from_config(cfg),
        override_paths=override_paths(cfg),
        objective_entrypoint=None,
    )
    return params_hash({"k": 1e-4}, context=context)


def _warning_of_a_search_that_ran_out(caplog) -> str:
    space = ParameterSpace(
        [
            CalibParameter(name="x", lower=-1.0, upper=1.0),
            CalibParameter(name="y", lower=-1.0, upper=1.0),
        ]
    )
    optimizer = build_optimizer("scipy_nelder_mead", space, seed=1, xatol=0.0, fatol=0.0)
    rng = np.random.default_rng(5)

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        return result_of(sugg, float(rng.uniform(1.0, 2.0)))

    with caplog.at_level(logging.WARNING):
        run_engine(space, optimizer, evaluate, 12)
    (record,) = [r for r in caplog.records if "did NOT converge" in r.getMessage()]
    return record.getMessage()


def test_a_larger_budget_replays_and_the_warning_says_so(caplog) -> None:
    assert _hash__not_converged(max_trials=500) == _hash__not_converged()

    message = _warning_of_a_search_that_ran_out(caplog)
    assert "Raise max_trials" in message
    assert "replays the trials already solved" in message


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("precision", {"precision": 0.1}),
        ("seed", {"seed": 4}),
        ("method_options", {"method_options": {"fatol": 1e-3}}),
        ("method", {"method": "random_search", "precision": None, "method_options": {}}),
    ],
)
def test_what_the_warning_names_beside_the_budget_is_outside_the_key(name, change, caplog) -> None:
    assert _hash__not_converged(**change) == _hash__not_converged()

    message = _warning_of_a_search_that_ran_out(caplog)
    assert name in message
    sentence = next(s for s in message.split(".") if name in s)
    assert "values already solved" in sentence
    assert "cache key" not in sentence
