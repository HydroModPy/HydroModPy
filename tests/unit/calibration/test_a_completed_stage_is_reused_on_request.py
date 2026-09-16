"""A phase already completed in a resumed chain is not solved twice.

`reuse_completed_phases` is off by default: a fresh staged run always solves
every phase, exactly as before. Turned on together with a
``resume_root_session_id``, a phase already ``completed`` in that chain is read
back from disk instead -- but only when its recorded fingerprint can be
reproduced under this run's own model, mesh and input files
(``hydromodpy.calibration.runners.resume.fingerprint_matches``). A session
whose fingerprint no longer matches is not the same problem, and the phase is
solved again rather than trusted.

The solver never runs here: :func:`run_calibration_core` and
:func:`prepare_trials` are replaced by a recorder, same as
``test_staged_runner.py``. What is faked in addition is
:func:`build_cache_context`, so the "fingerprint" a test controls is a single
marker instead of a real model/mesh digest -- the machinery under test is the
comparison, not the digest itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.results.catalog import Catalog

_ROOT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_STEADY = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

K_PATH = "flow.param.K.field.value"
K_TOML = 1e-5
SY_TOML = 0.1
K_SOLVED = 2.5e-5
SY_SOLVED = 0.07
K_FROM_DISK = 9.9e-5

BASE = """
[calibration]
method = "grid"
max_iter = 4
reuse_completed_phases = {reuse}

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0]

[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]

[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy"]
objective_blocks = ["q_block"]
depends_on = "steady_k"
"""


def _write(tmp_path: Path, *, reuse: bool) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(BASE.format(reuse=str(reuse).lower()), encoding="utf-8")
    return path


def _baseline() -> SimpleNamespace:
    return SimpleNamespace(
        flow=SimpleNamespace(
            param=SimpleNamespace(
                K=SimpleNamespace(field=SimpleNamespace(value=K_TOML)),
                Sy=SimpleNamespace(field=SimpleNamespace(value=SY_TOML)),
            )
        )
    )


class FakeRunner:
    """Stands in for the preparation and the calibration loop of one phase."""

    def __init__(self) -> None:
        self.values = {"K": K_SOLVED, "Sy": SY_SOLVED}
        self.calls: list[SimpleNamespace] = []

    @property
    def phases_run(self) -> list[str]:
        return [call.chain.phase_name for call in self.calls]

    def prepare_trials(
        self,
        cfg_path: Path,
        *,
        override_paths,
        steps=None,
        parameter_space=None,
        config_overrides=None,
    ) -> TrialContext:
        baseline = _baseline()
        for dotted, value in (config_overrides or {}).items():
            set_by_path(baseline, str(dotted), value)
        return TrialContext(
            base_cfg=baseline,
            ctx=None,
            earliest=0,
            downstream_steps=(),
            override_paths=dict(override_paths),
            workspace=cfg_path.parent,
            cfg_path=cfg_path,
            parameter_space=parameter_space,
        )

    def run_calibration_core(
        self,
        cfg,
        trial_ctx,
        *,
        workspace,
        space,
        project_label="calibration",
        cfg_path=None,
        metric_fn=None,
        objective=None,
        store_factory=None,
        chain=None,
        start_at=None,
    ) -> CalibrationReport:
        self.calls.append(SimpleNamespace(cfg=cfg, chain=chain, trial_ctx=trial_ctx))
        best = {name: self.values[name] for name in cfg.parameters}
        return CalibrationReport(
            session_id=chain.session_id,
            method=cfg.method,
            n_iterations=cfg.max_iter,
            best_objective=0.1,
            best_sim_id=None,
            duration_s=1.0,
            save_runs=cfg.save_runs,
            promoted=0,
            best_parameters=best,
            workspace=workspace,
        )


def _apply(monkeypatch: pytest.MonkeyPatch, fake: FakeRunner, *, marker: str) -> None:
    """Fake the solver and the fingerprint's raw material; keep the guard real."""
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)
    monkeypatch.setattr(staged_runner, "build_cache_context", lambda **kwargs: {"marker": marker})


def _completed_steady_session(catalog: Catalog, *, recorded_marker: str) -> None:
    """Write a `steady_k` session that finished, its best trial hashed under `recorded_marker`."""
    catalog._backend.execute(
        "INSERT INTO calibration_sessions "
        "(session_id, project, method, objective_name, n_iterations, best_objective, config, "
        "started_at, status_id, root_session_id, phase_name, phase_index) "
        "VALUES (?, 'p', 'bisection', 'nse', 3, 0.01, '{}', current_timestamp, "
        "(SELECT id FROM statuses WHERE code = 'completed'), ?, 'steady_k', 0)",
        [_STEADY, _ROOT],
    )
    recorded_hash = params_hash({"K": K_FROM_DISK}, context={"marker": recorded_marker})
    catalog._backend.execute(
        "INSERT INTO calibration_iterations "
        "(session_id, iteration, parameters, objective_value, status, params_hash) "
        "VALUES (?, 0, ?, 0.01, 'completed', ?)",
        [_STEADY, json.dumps({"K": K_FROM_DISK}), recorded_hash],
    )


class TestTheFlagIsOffByDefault:
    def test_a_completed_session_is_ignored_and_the_phase_runs(self, tmp_path, monkeypatch) -> None:
        cfg_path = _write(tmp_path, reuse=False)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        catalog = Catalog(tmp_path / "index.duckdb")
        factory_calls: list[object] = []
        try:
            _completed_steady_session(catalog, recorded_marker="v1")

            report = run_staged_calibration(
                cfg_path,
                resume_root_session_id=_ROOT,
                store_factory=lambda ws, persistence: (factory_calls.append(ws), catalog)[1],
            )
        finally:
            catalog.close()

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert factory_calls == []


class TestAMatchingFingerprintIsReused:
    def test_the_completed_phase_is_read_back_and_the_next_one_solves(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, reuse=True)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        catalog = Catalog(tmp_path / "index.duckdb")
        try:
            _completed_steady_session(catalog, recorded_marker="v1")

            report = run_staged_calibration(
                cfg_path,
                resume_root_session_id=_ROOT,
                store_factory=lambda ws, persistence: catalog,
            )
        finally:
            catalog.close()

        assert fake.phases_run == ["transient_sy"]
        assert report.reused_from_disk == ("steady_k",)
        assert report.phases[0].session_id == _STEADY
        assert report.frozen[0].name == "K"
        assert report.frozen[0].value == pytest.approx(K_FROM_DISK)

    def test_the_reused_value_is_frozen_into_the_phase_that_still_solves(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, reuse=True)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        catalog = Catalog(tmp_path / "index.duckdb")
        try:
            _completed_steady_session(catalog, recorded_marker="v1")

            run_staged_calibration(
                cfg_path,
                resume_root_session_id=_ROOT,
                store_factory=lambda ws, persistence: catalog,
            )
        finally:
            catalog.close()

        (transient_call,) = fake.calls
        assert transient_call.trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(
            K_FROM_DISK
        )


class TestAMismatchedFingerprintIsResolved:
    def test_a_different_context_today_re_solves_instead_of_trusting_it(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, reuse=True)
        fake = FakeRunner()
        # This run's own model/mesh/input-file context ("v2") is not the one the
        # historical session was scored under ("v1" below): not the same problem.
        _apply(monkeypatch, fake, marker="v2")
        catalog = Catalog(tmp_path / "index.duckdb")
        try:
            _completed_steady_session(catalog, recorded_marker="v1")

            report = run_staged_calibration(
                cfg_path,
                resume_root_session_id=_ROOT,
                store_factory=lambda ws, persistence: catalog,
            )
        finally:
            catalog.close()

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert report.frozen[0].name == "K"
        assert report.frozen[0].value == pytest.approx(K_SOLVED)


class TestTheBaselineIsFrozenBeforeTheFingerprintIsAsked:
    """The question has to be asked of the same model the answer was recorded on.

    A phase's recorded hash was computed with every upstream freeze already
    written into the baseline. Asking whether that phase may be reused before
    applying those freezes compares two different models, so the answer is no
    for a rerun that is in fact identical, and every phase past the first is
    needlessly re-solved. The fault is invisible to a test that stubs the
    context out: it shows only in the ORDER of the two operations.
    """

    def test_the_upstream_freeze_is_already_applied_when_reuse_is_considered(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, reuse=True)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        seen: list[object] = []

        def spy(**kwargs):
            # What the baseline holds at the moment the fingerprint is computed.
            seen.append(kwargs["trial_ctx"].base_cfg.flow.param.K.field.value)
            return None

        monkeypatch.setattr(staged_runner, "_reuse_from_disk", spy)
        catalog = Catalog(tmp_path / "index.duckdb")
        try:
            _completed_steady_session(catalog, recorded_marker="v1")
            run_staged_calibration(
                cfg_path,
                resume_root_session_id=_ROOT,
                store_factory=lambda ws, persistence: catalog,
            )
        finally:
            catalog.close()

        # Two phases were considered; the second one saw the first one's freeze.
        assert len(seen) == 2
        assert seen[1] == pytest.approx(K_SOLVED)
