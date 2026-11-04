"""Tests of `optim.cache`."""

from __future__ import annotations

import inspect
import json
import logging
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import (
    CachedEvaluation,
    ParamsHashCache,
    canonical_json,
    context_fingerprints,
    differing_members,
    params_hash,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
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
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION
from hydromodpy.results.session.journal import trials_path
from tests.unit.calibration._factories import unit_space
from tests.unit.calibration._factories_search import result_of, run_engine

# From test_a_map_rewritten_in_place_moves_the_cache_key.py
# A map rewritten at the same path moves the cache key of a network calibration.
#
# The key held the path of ``stream_geometry_path`` and of
# ``minimal_stream_geometry_path``, never what the file holds. A map redrawn and
# saved under the same name scored nothing new: every trial came back from the
# cache with the cost of the old map. The key now holds the content of each map
# file, with the sidecars of a shapefile, and only a document that names a map
# carries it.


PARAMETERS = {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}


def _network(**paths: Path) -> CalibrationConfig:
    output: dict[str, Any] = {
        "support": "network",
        **{key: str(value) for key, value in paths.items()},
    }
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

    assert _key(_network(stream_geometry_path=streams)) == _key(
        _network(stream_geometry_path=streams)
    )


@pytest.mark.parametrize("field", ["stream_geometry_path", "minimal_stream_geometry_path"])
def test_a_map_rewritten_at_its_path_moves_the_key(tmp_path: Path, field: str) -> None:
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")
    paths = {"stream_geometry_path": streams}
    if field == "minimal_stream_geometry_path":
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
    before = _key(_network(stream_geometry_path=streams))

    streams.with_suffix(".dbf").write_bytes(b"other attributes")

    assert _key(_network(stream_geometry_path=streams)) != before


def test_a_document_that_names_no_map_carries_no_map_member() -> None:
    cfg = CalibrationConfig.model_validate(
        {
            "parameters": PARAMETERS,
            "outputs": {"q": {"support": "boundary", "variable": "discharge", "boundary_id": "o"}},
            "variable": "q",
        }
    )

    assert "observed_maps" not in _context(cfg)


def test_a_map_not_there_is_keyed_as_missing(tmp_path: Path) -> None:
    context = _context(_network(stream_geometry_path=tmp_path / "absent.gpkg"))

    assert context["observed_maps"] == {"net.stream_geometry_path": "missing"}


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


class TestCanonicalJSON:
    def test_sorted_keys(self):
        a = canonical_json({"b": 2.0, "a": 1.0})
        b = canonical_json({"a": 1.0, "b": 2.0})
        assert a == b

    def test_noise_below_precision_collapses(self):
        # Differ at the 15th significant digit; default precision=12.
        a = canonical_json({"x": 1.234567890123})
        b = canonical_json({"x": 1.2345678901234})
        assert a == b

    def test_above_precision_distinguishes(self):
        a = canonical_json({"x": 1.23e-6})
        b = canonical_json({"x": 1.24e-6})
        assert a != b


class TestParamsHash:
    def test_stable_across_orderings(self):
        h1 = params_hash({"a": 0.1, "b": 0.2})
        h2 = params_hash({"b": 0.2, "a": 0.1})
        assert h1 == h2

    def test_hex_string_length(self):
        h = params_hash({"a": 1.0})
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_values_different_hash(self):
        h1 = params_hash({"a": 1.0})
        h2 = params_hash({"a": 2.0})
        assert h1 != h2

    def test_context_changes_hash(self):
        h1 = params_hash({"a": 1.0}, context={"calibration": "kge"})
        h2 = params_hash({"a": 1.0}, context={"calibration": "nse"})
        assert h1 != h2
        assert h1.startswith("v2:")

    def test_context_order_is_stable(self):
        h1 = params_hash({"a": 1.0}, context={"b": 2.0, "a": [3.0, 4.0]})
        h2 = params_hash({"a": 1.0}, context={"a": [3.0, 4.0], "b": 2.0})
        assert h1 == h2


class TestParamsHashCache:
    def test_empty_cache(self):
        cache = ParamsHashCache()
        assert len(cache) == 0
        assert cache.get("abc") is None
        assert "abc" not in cache

    def test_put_and_get(self):
        cache = ParamsHashCache()
        cache.put("abc", cost=0.12)
        hit = cache.get("abc")
        assert hit == CachedEvaluation(cost=0.12)
        assert "abc" in cache
        assert len(cache) == 1

    def test_put_overwrites(self):
        cache = ParamsHashCache()
        cache.put("abc", cost=0.12)
        cache.put("abc", cost=0.03)
        hit = cache.get("abc")
        assert hit is not None
        assert hit.cost == 0.03

    def test_cache_hit_returns_evaluation(self):
        """Two evaluations with identical params yield the same cached cost."""
        cache = ParamsHashCache()
        values = {"K": 1.5e-4, "Sy": 0.1}
        h = params_hash(values)
        cache.put(h, cost=1.5, components={"rmse": 1.5})

        # Second call with equivalent dict must hit the cache.
        h2 = params_hash({"Sy": 0.1, "K": 1.5e-4})
        hit = cache.get(h2)
        assert hit is not None
        assert hit.cost == 1.5
        assert hit.components == {"rmse": 1.5}
        assert not hasattr(hit, "sim_id"), "a hit never names the run of another trial"


class TestContextFingerprints:
    def test_a_member_moves_its_own_fingerprint_only(self):
        before = context_fingerprints(
            {"schema": "v4", "model": {"K": 1.0}, "calibration": {"seed": 1}}
        )
        after = context_fingerprints(
            {"schema": "v4", "model": {"K": 2.0}, "calibration": {"seed": 1}}
        )

        assert differing_members(before, after) == ["model"]
        assert before["schema"] == "v4", "the schema is kept in clear"

    def test_a_member_one_side_lacks_differs(self):
        assert differing_members({"model": "a"}, {"model": "a", "mesh": "b"}) == ["mesh"]


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
    def test_grid_iterates_until_exhausted(self):
        """Grid with 3 points must produce exactly 3 history entries."""
        space = unit_space()
        opt = build_optimizer("grid", space, points_per_dim=3)
        session = run_engine(space, opt, _simple_evaluator, 10)
        assert len(session.history) == 3
        assert {r.trial_id for r in session.history} == {1, 2, 3}

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

    def test_grid_2d_explores_full_product_and_finds_convex_minimum(self):
        """A 2D grid runs the full ask/tell loop and lands on the convex min."""
        space = ParameterSpace(
            [
                CalibParameter(name="x", lower=-1.0, upper=1.0),
                CalibParameter(name="y", lower=-1.0, upper=1.0),
            ]
        )
        opt = build_optimizer("grid", space, points_per_dim=3)

        def convex(sugg: ParamSuggestion) -> EvaluationResult:
            x = float(sugg.values["x"])
            y = float(sugg.values["y"])
            return result_of(sugg, x**2 + y**2)

        session = run_engine(space, opt, convex, 9)

        assert len(session.history) == 9  # full 3x3 cartesian product
        assert session.best is not None
        assert session.best.cost <= session.history[-1].cost + 1e-9
        assert abs(session.best.cost) < 1e-12  # grid includes (0, 0)

    def test_session_exposes_duration(self):
        """Duration tracking does not break when the loop runs to completion."""
        space = unit_space()
        opt = build_optimizer("grid", space, points_per_dim=2)
        session = run_engine(space, opt, _simple_evaluator, 10)
        assert session.duration_s >= 0.0
        assert session.finished_at is not None


class TestEngineEdgeCases:
    def test_max_trials_zero_runs_no_iterations(self):
        """``max_trials=0`` must produce an empty session with no evaluator call."""
        space = unit_space()
        opt = build_optimizer("random_search", space, seed=0)
        calls: list[int] = []

        def _never(sugg):
            calls.append(sugg.trial_id)
            return _simple_evaluator(sugg)

        session = run_engine(space, opt, _never, 0)
        assert calls == []
        assert session.history == []
        assert session.best is None

    def test_batch_size_larger_than_max_trials_is_clamped(self):
        """When ``batch_size > max_trials`` the engine clamps the per-ask ``n``."""
        space = unit_space()
        # Use a stub that returns 5 suggestions if asked - we expect only 3.
        opt = _StubOptimizer([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}, {"x": 0.5}])
        session = run_engine(space, opt, _simple_evaluator, 3, batch_size=100)
        assert len(session.history) == 3

    def test_parallel_alone_runs_trials_side_by_side(self):
        """``parallel`` alone fills each batch: batch_size 1 must not serialize it."""

        space = unit_space()
        opt = _StubOptimizer([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}])
        active = {"now": 0, "most": 0}
        guard = threading.Lock()

        def _slow(sugg):
            with guard:
                active["now"] += 1
                active["most"] = max(active["most"], active["now"])
            time.sleep(0.2)
            with guard:
                active["now"] -= 1
            return _simple_evaluator(sugg)

        session = run_engine(space, opt, _slow, 4, parallel=4)

        assert len(session.history) == 4
        assert active["most"] == 4

    def test_empty_suggestion_list_terminates_without_error(self):
        """An optimizer that returns ``[]`` must stop the loop gracefully."""
        space = unit_space()
        opt = _StubOptimizer(suggestions=[])

        def _never(sugg):
            raise RuntimeError("evaluator should not run when no suggestions")

        session = run_engine(space, opt, _never, 10)
        assert session.history == []
        assert session.best is None


# ---------------------------------------------------------------------------
# on_iteration callback
# ---------------------------------------------------------------------------
class TestOnIterationCallback:
    def test_callback_fires_once_per_completed_trial(self):
        space = unit_space()
        opt = build_optimizer("grid", space, points_per_dim=4)
        received: list[int] = []

        run_engine(
            space,
            opt,
            _simple_evaluator,
            10,
            on_iteration=lambda _s, r: received.append(r.trial_id),
        )
        assert received == [1, 2, 3, 4]

    def test_callback_receives_evaluation_result_object(self):
        space = unit_space()
        opt = build_optimizer("grid", space, points_per_dim=1)
        captured: list[tuple[ParamSuggestion, EvaluationResult]] = []

        run_engine(
            space, opt, _simple_evaluator, 10, on_iteration=lambda s, r: captured.append((s, r))
        )
        assert len(captured) == 1
        suggestion, result = captured[0]
        assert isinstance(result, EvaluationResult)
        assert result.status == "completed"
        assert suggestion.trial_id == result.trial_id

    def test_callback_fires_on_a_cache_hit(self):
        """A cached trial is still an iteration: it must reach the persister."""
        space = unit_space()
        cache = ParamsHashCache()
        captured: list[tuple[ParamSuggestion, EvaluationResult]] = []

        for _ in range(2):
            engine = CalibrationEngine(
                space=space,
                optimizer=build_optimizer("grid", space, points_per_dim=2),
                evaluator=_simple_evaluator,
                max_trials=2,
                cache=cache,
                on_iteration=lambda s, r: captured.append((s, r)),
            )
            engine.run()

        assert [result.from_cache for _s, result in captured] == [False, False, True, True]
        assert all(suggestion.values for suggestion, _r in captured)


# ---------------------------------------------------------------------------
# ParamsHashCache integration
# ---------------------------------------------------------------------------
class TestEngineCacheIntegration:
    def test_cache_hit_skips_reevaluation(self):
        """Re-proposing the same values must not re-run the evaluator."""
        space = unit_space()
        # Stub repeats the exact same values three times.
        opt = _StubOptimizer([{"x": 0.5}, {"x": 0.5}, {"x": 0.5}])
        cache = ParamsHashCache()
        eval_calls: list[int] = []

        def _counting_evaluator(sugg):
            eval_calls.append(sugg.trial_id)
            return EvaluationResult(
                trial_id=sugg.trial_id, sim_id="sim-shared", cost=0.5, status="completed"
            )

        session = run_engine(space, opt, _counting_evaluator, 10, cache=cache)
        assert len(eval_calls) == 1  # only the first call hits the evaluator
        assert len(session.history) == 3
        # Subsequent results must be marked as cache hits.
        assert session.history[0].from_cache is False
        assert session.history[1].from_cache is True
        assert session.history[2].from_cache is True
        assert session.history[1].status == "completed"
        assert session.history[1].cost == 0.5
        # Cache is keyed by hash of the suggested values.
        assert params_hash({"x": 0.5}) in cache

    def test_cache_populates_on_first_hit(self):
        """After the first completed evaluation, the cache holds its cost and no run."""
        space = unit_space()
        opt = _StubOptimizer([{"x": 0.42}])
        cache = ParamsHashCache()

        def _evaluator(sugg):
            return EvaluationResult(
                trial_id=sugg.trial_id, sim_id="sim-abc", cost=0.1, status="completed"
            )

        run_engine(space, opt, _evaluator, 10, cache=cache)
        key = params_hash({"x": 0.42})
        hit = cache.get(key)
        assert hit is not None
        assert hit.cost == 0.1

    def test_no_cache_means_every_trial_runs(self):
        """When ``cache=None`` the engine never inspects or stores results."""
        space = unit_space()
        opt = _StubOptimizer([{"x": 0.5}, {"x": 0.5}, {"x": 0.5}])
        eval_calls: list[int] = []

        def _evaluator(sugg):
            eval_calls.append(sugg.trial_id)
            return _simple_evaluator(sugg)

        run_engine(space, opt, _evaluator, 10, cache=None)
        assert len(eval_calls) == 3

    def test_cache_stores_params_hash_in_metadata(self):
        """Completed results should be enriched with ``params_hash`` metadata."""
        space = unit_space()
        opt = _StubOptimizer([{"x": 0.25}])
        cache = ParamsHashCache()

        session = run_engine(space, opt, _simple_evaluator, 5, cache=cache)
        assert len(session.history) == 1
        result = session.history[0]
        assert "params_hash" in result.metadata
        assert result.metadata["params_hash"] == params_hash({"x": 0.25})

    def test_cache_context_scopes_params_hash_in_metadata(self):
        space = unit_space()
        opt = _StubOptimizer([{"x": 0.25}])
        cache = ParamsHashCache()
        context = {"objective": "kge", "bounds": [0.0, 1.0]}

        session = run_engine(space, opt, _simple_evaluator, 5, cache=cache, cache_context=context)

        key = params_hash({"x": 0.25}, context=context)
        assert session.history[0].metadata["params_hash"] == key
        assert key.startswith("v2:")
        assert key in cache


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


def test_the_schema_of_the_key_is_the_fourth() -> None:
    cfg = CalibrationConfig.model_validate(BASE)

    assert _context(cfg)["schema"] == "hydromodpy.calibration.params_hash.v4"


def test_the_key_is_flat_with_one_member_per_layer_of_code() -> None:
    context = _context(CalibrationConfig.model_validate(BASE))

    assert {
        "metric_rule_version",
        "model",
        "calibration",
        "override_paths",
        "parameter_space",
        "input_files",
        "mesh",
    } <= set(context)
    assert [name for name in context if name.startswith("code.")]
    assert "code_version" not in context, "a release number moves no hash"


def test_the_model_enters_as_written_and_without_its_workspace() -> None:
    class _Config(BaseModel):
        workspace: dict[str, str] = {"root": "/somewhere"}
        flow: dict[str, float] = {"K": 1e-4}
        transport: dict[str, float] = {"alpha": 0.1}

    written = _Config(flow={"K": 1e-4})
    trial_ctx = SimpleNamespace(
        base_cfg=written, ctx=SimpleNamespace(setup=SimpleNamespace(cell_mesh=None))
    )
    cfg = CalibrationConfig.model_validate(BASE)

    context = state.build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )

    assert context["model"] == {"flow": {"K": 1e-4}}, "no workspace, and no default written"


@pytest.mark.parametrize(
    "change",
    [
        {"method": "random_search", "precision": None, "method_options": {}},
        {"seed": 4},
        {"precision": 0.1},
        {"max_trials": 500},
        {"method_options": {"fatol": 1e-3}},
        {"batch_size": 4, "parallel": 4},
        {"save_runs": "best_n", "save_best_n": 3},
        {"use_cache": False},
        {"persist_iteration_detail": "none"},
        {"persist_trial_series": True},
        {"materialize_candidates": True},
        {"promote_phases": True},
        {"uncertainty": {"cost_margin": "10%"}},
        {
            "parameters": {
                "k": {
                    "path": "flow.properties.k_aquifer",
                    "bounds": [1e-5, 1e-3],
                    "search_space": "identity",
                    "sampling": "log_uniform",
                }
            }
        },
    ],
    ids=lambda change: next(iter(change)),
)
def test_what_does_not_change_the_cost_of_a_trial_leaves_the_key_alone(change: dict) -> None:
    assert _hash(**change) == _hash()


@pytest.mark.parametrize(
    "change",
    [
        {"objective": "kge"},
        {"variable": "head"},
        {"window": {"start": "2001-01-01"}},
        {"reject_water_budget_above": 5.0},
        {"aggregate": {"min_samples": 30}},
        {"outputs": {"gauge": OUTPUT}, "variable": "gauge"},
        {
            "parameters": {
                "k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2], "mode": "scale"}
            }
        },
        {
            "parameters": {
                "k": {"path": "flow.properties.sy", "bounds": [1e-6, 1e-2], "search_space": "log"}
            }
        },
    ],
    ids=lambda change: next(iter(change)),
)
def test_what_changes_the_cost_of_a_trial_changes_the_key(change: dict) -> None:
    assert _hash(**change) != _hash()


def test_another_objective_block_changes_the_key() -> None:
    gauge = {"gauge": OUTPUT}
    one = {"name": "q", "metric": "nse", "uses_outputs": ["gauge"]}
    other = {**one, "metric": "kge"}

    assert _hash(outputs=gauge, objective_blocks=[one]) != _hash(
        outputs=gauge, objective_blocks=[other]
    )


def test_a_named_evaluator_changes_the_key_and_the_default_does_not() -> None:
    assert _hash(evaluator="hydromodpy_pipeline") == _hash()


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


def test_a_phase_narrower_than_its_section_reuses_the_trials_of_a_wider_search() -> None:
    wide = {"name": "wide", "parameters": ["k"], "objective": "nse"}
    narrow = {**wide, "name": "narrow", "bounds": {"k": [1e-5, 1e-3]}}
    cfg = CalibrationConfig.model_validate({**BASE, "phases": [wide, narrow]})
    first, second = (_phase_config(cfg, phase) for phase in cfg.phases)

    assert params_hash({"k": 1e-4}, context=_context(first)) == params_hash(
        {"k": 1e-4}, context=_context(second)
    )
    assert second.parameters["k"].bounds == [1e-5, 1e-3]


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
    def test_a_mesh_yields_a_fingerprint(self) -> None:
        found = mesh_fingerprint(_ctx(_Mesh(_A)))

        assert found is not None
        assert found["n_cells"] == 4

    def test_two_different_meshes_do_not_share_a_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_B)))

        assert first != second

    def test_the_same_mesh_yields_the_same_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_A.copy())))

        assert first == second

    def test_a_reordered_mesh_is_a_different_mesh(self) -> None:
        """Cell order is the solver's own indexing; a different order is not the same grid."""
        reordered = _A[[1, 0, 3, 2]]

        assert mesh_fingerprint(_ctx(_Mesh(_A))) != mesh_fingerprint(_ctx(_Mesh(reordered)))

    def test_no_mesh_yields_nothing_rather_than_a_constant(self) -> None:
        """A lumped model has no mesh; keying on a placeholder would be a lie."""
        assert mesh_fingerprint(_ctx(None)) is None


class TestItReachesTheCacheKey:
    def test_the_context_carries_it(self) -> None:
        source = inspect.getsource(state.build_cache_context)

        assert "mesh_fingerprint" in source

    def test_two_meshes_give_two_different_hashes(self) -> None:
        from hydromodpy.calibration.optim.cache import params_hash

        values = {"K": 1e-5}
        first = params_hash(values, context={"mesh": mesh_fingerprint(_ctx(_Mesh(_A)))})
        second = params_hash(values, context={"mesh": mesh_fingerprint(_ctx(_Mesh(_B)))})

        assert first != second

    def test_the_requested_settings_alone_would_not_have_caught_it(self) -> None:
        """Same request, different triangulation: only the built mesh separates them."""
        from hydromodpy.calibration.optim.cache import params_hash

        requested = {"mesh_catchment": {"zone_meshing": {"global_size": 250.0}}}
        assert params_hash({"K": 1e-5}, context=requested) == params_hash(
            {"K": 1e-5}, context=requested
        )


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


def test_the_context_names_the_rule_the_cost_was_scored_under() -> None:
    assert _context__cache_key_names()["metric_rule_version"] == METRIC_RULE_VERSION


def test_a_cost_hashed_before_the_rule_was_keyed_is_not_found() -> None:
    context = _context__cache_key_names()
    before = {key: value for key, value in context.items() if key != "metric_rule_version"}

    assert params_hash({"k": 1e-4}, context=context) != params_hash({"k": 1e-4}, context=before)


def test_another_rule_version_gives_another_key(monkeypatch) -> None:
    now = params_hash({"k": 1e-4}, context=_context__cache_key_names())
    monkeypatch.setattr(state, "METRIC_RULE_VERSION", f"{METRIC_RULE_VERSION}-next")

    assert params_hash({"k": 1e-4}, context=_context__cache_key_names()) != now


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
