"""What a calibration run in phases hands from one stage to the next.

The solver never runs here: :func:`run_calibration_core` and
:func:`prepare_trials` are replaced by a recorder, so what is under test is
the staging itself -- the order of the phases, the configuration each one
runs under, where a frozen value lands, and the chain of sessions.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError, ConfigValidationError

K_PATH = "flow.param.K.field.value"
SY_PATH = "flow.param.Sy.field.value"
K_TOML = 1e-5
SY_TOML = 0.1
K_CALIBRATED = 2.5e-5
SY_CALIBRATED = 0.07

BASE = """
[calibration]
method = "grid"
max_iter = 4

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "Q_STATION"

[calibration.outputs.h]
variable = "head"
support = "point"
x = 100.0
y = 0.0
observes = "H_STATION"

# One cost in m3/s and one in metres: both are normalised, because a sum of
# two units would let their magnitudes set the weighting.
[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]
normalize_cost = true

[[calibration.objective_blocks]]
name = "h_block"
metric = "rmse"
uses_outputs = ["h"]
normalize_cost = true
"""

TWO_PHASES = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
outputs = ["q"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy"]
objective_blocks = ["h_block"]
depends_on = "steady_k"
"""

NO_FREEZE = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
objective_blocks = ["q_block"]
freeze_on_success = false

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy", "K"]
objective_blocks = ["h_block"]
depends_on = "steady_k"
"""

# Same two phases, but the second one is not written against what the first
# freezes. A phase nobody builds on may fail and hand nothing over; that is
# what the two "freezes nothing" tests below are about, and it is only
# observable on a table where no phase depends on the one that failed.
INDEPENDENT = """
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
objective_blocks = ["h_block"]
parameters = ["Sy"]
"""

# ``rel_tol`` is a setting of the one-dimensional root search. The second phase
# searches on a grid, which has no such knob, so this table cannot build the
# calibration of its second phase -- and nothing says so until its turn.
BAD_SECOND_PHASE = """
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
objective_blocks = ["h_block"]
parameters = ["Sy"]
optimizer_kwargs = { rel_tol = 0.01 }
"""


def _write(tmp_path: Path, phases: str = TWO_PHASES) -> Path:
    """Write a calibration TOML and return its path."""
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + phases, encoding="utf-8")
    return path


def _baseline() -> SimpleNamespace:
    """A configuration tree the calibrated paths can be written into."""
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

    def __init__(self, *, best_objective: float | None = 0.25) -> None:
        self.best_objective = best_objective
        self.values = {"K": K_CALIBRATED, "Sy": SY_CALIBRATED}
        self.prepared: list[dict[str, str]] = []
        self.overridden: list[dict[str, object]] = []
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
        self.prepared.append(dict(override_paths))
        self.overridden.append(dict(config_overrides or {}))
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
        self.calls.append(
            SimpleNamespace(
                cfg=cfg,
                trial_ctx=trial_ctx,
                baseline=trial_ctx.base_cfg,
                space=space,
                workspace=workspace,
                chain=chain,
                start_at=start_at,
                seed=cfg.seed,
            )
        )
        best = {name: self.values[name] for name in cfg.parameters}
        return CalibrationReport(
            session_id=chain.session_id,
            method=cfg.method,
            n_iterations=cfg.max_iter,
            best_objective=self.best_objective,
            best_sim_id=None,
            duration_s=1.0,
            save_runs=cfg.save_runs,
            promoted=0,
            best_parameters=None if self.best_objective is None else best,
            workspace=workspace,
        )


@pytest.fixture
def runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)
    return fake


# -- order and per-phase configuration --------------------------------------


def test_the_phases_run_in_declaration_order(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert runner.phases_run == ["steady_k", "transient_sy"]
    assert [phase.name for phase in report.phases] == ["steady_k", "transient_sy"]
    assert [phase.index for phase in report.phases] == [0, 1]


def test_each_phase_runs_the_search_it_declares(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    steady, transient = (call.cfg for call in runner.calls)
    assert (steady.method, steady.max_iter) == ("bisection", 12)
    assert (transient.method, transient.max_iter) == ("grid", 30)
    assert list(steady.parameters) == ["K"]
    assert list(transient.parameters) == ["Sy"]
    assert runner.calls[0].space.names == ("K",)
    assert runner.calls[1].space.names == ("Sy",)


def test_a_phase_config_is_an_ordinary_mono_phase_calibration(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    assert all(call.cfg.phases is None for call in runner.calls)


def test_each_phase_scores_only_on_the_blocks_it_names(tmp_path, runner) -> None:
    # A staged table has to say this per phase: a phase that named nothing used
    # to inherit every declared block, so the transient stage was scored on the
    # steady stage's criterion too. The schema now refuses that silence.
    run_staged_calibration(_write(tmp_path))

    steady, transient = (call.cfg for call in runner.calls)
    assert list(steady.outputs) == ["q"]
    assert [block.name for block in steady.objective_blocks] == ["q_block"]
    assert [block.name for block in transient.objective_blocks] == ["h_block"]


def test_a_phase_that_names_no_output_gets_the_ones_its_blocks_read(tmp_path, runner) -> None:
    # The transient phase selects a block and no output. It used to inherit
    # every declared one, so the steady stage's discharge was extracted from
    # each of its trials and entered no cost. Worse where the two stages score
    # different families: a network output handed to a stage scored on a series
    # is refused outright, and the whole staged file stopped running.
    run_staged_calibration(_write(tmp_path))

    _, transient = (call.cfg for call in runner.calls)

    assert list(transient.outputs) == ["h"]


# -- freezing ----------------------------------------------------------------


def test_a_frozen_parameter_leaves_the_search_of_the_next_phase(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    transient = runner.calls[1]
    assert "K" not in transient.cfg.parameters
    assert "K" not in transient.space.names


def test_a_frozen_parameter_enters_the_baseline_of_the_next_phase(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    steady, transient = runner.calls
    assert steady.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_CALIBRATED)
    assert transient.baseline.flow.param.Sy.field.value == pytest.approx(SY_TOML)


def test_the_prepared_pipeline_treats_the_frozen_path_as_varying(tmp_path, runner) -> None:
    # A preparation step reading the frozen path has to re-run per trial,
    # otherwise the prepared prefix would keep the value the TOML declares.
    run_staged_calibration(_write(tmp_path))

    assert runner.prepared[0] == {"K": K_PATH}
    assert runner.prepared[1] == {"Sy": SY_PATH, "K": K_PATH}


def test_the_report_names_each_frozen_value_with_its_path(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert [item.to_dict() for item in report.frozen] == [
        {
            "name": "K",
            "path": K_PATH,
            "value": pytest.approx(K_CALIBRATED),
            "mode": "replace",
            "phase": "steady_k",
        },
        {
            "name": "Sy",
            "path": SY_PATH,
            "value": pytest.approx(SY_CALIBRATED),
            "mode": "replace",
            "phase": "transient_sy",
        },
    ]
    assert report.to_dict()["phases"][0]["frozen"][0]["path"] == K_PATH


def test_freeze_on_success_false_leaves_the_next_phase_free_to_move_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path, NO_FREEZE))

    transient = runner.calls[1]
    assert "K" in transient.cfg.parameters
    assert "K" in transient.space.names
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert report.phases[0].frozen == ()


def test_a_phase_that_did_not_converge_freezes_nothing(tmp_path, monkeypatch) -> None:
    # No phase of INDEPENDENT is written against what another one freezes, so
    # the chain survives the failure and what it hands over stays observable.
    fake = FakeRunner(best_objective=None)
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    report = run_staged_calibration(_write(tmp_path, INDEPENDENT))

    assert report.frozen == ()
    assert fake.calls[1].baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert "K" not in fake.prepared[1]


def test_a_best_cost_at_the_failure_sentinel_is_not_a_convergence(tmp_path, monkeypatch) -> None:
    from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST

    fake = FakeRunner(best_objective=FAILED_EVAL_COST)
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    report = run_staged_calibration(_write(tmp_path, INDEPENDENT))

    assert report.frozen == ()


def test_a_freezing_phase_that_produced_no_result_stops_the_chain(tmp_path, monkeypatch) -> None:
    """TWO_PHASES writes ``transient_sy`` against what ``steady_k`` freezes.

    When ``steady_k`` hands nothing over, running ``transient_sy`` would
    calibrate it against the values the TOML declares. Its dependency did run,
    so nothing else in the chain is in a position to notice.
    """
    fake = FakeRunner(best_objective=None)
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    with pytest.raises(CalibrationError) as refusal:
        run_staged_calibration(_write(tmp_path))

    assert fake.phases_run == ["steady_k"]
    message = str(refusal.value)
    assert "steady_k" in message
    assert "transient_sy" in message
    assert fake.calls[0].chain.session_id in message


# -- selecting one phase -----------------------------------------------------


def test_selecting_a_phase_whose_dependency_did_not_run_is_refused(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="steady_k"):
        run_staged_calibration(_write(tmp_path), phase="transient_sy")

    assert runner.calls == []


def test_selecting_an_independent_phase_runs_only_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path), phase="steady_k")

    assert runner.phases_run == ["steady_k"]
    assert [phase.index for phase in report.phases] == [0]


def test_selecting_an_undeclared_phase_lists_the_declared_ones(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="transient_sy"):
        run_staged_calibration(_write(tmp_path), phase="nowhere")


def test_a_calibration_without_phases_is_refused(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="run_calibration_cli"):
        run_staged_calibration(_write(tmp_path, ""))


# -- what is checked before the first solve ----------------------------------


def test_a_phase_that_cannot_be_built_is_refused_before_the_first_one_runs(
    tmp_path, runner
) -> None:
    """The phase table validates against the calibration, not against itself.

    ``transient_sy`` narrows to a grid search while carrying a setting of the
    root search, so the calibration it builds declares an optimizer keyword its
    own method refuses. The refusal used to wait for its turn, by which time
    ``steady_k`` had spent its twelve solves.
    """
    with pytest.raises(ConfigValidationError, match="transient_sy"):
        run_staged_calibration(_write(tmp_path, BAD_SECOND_PHASE))

    assert runner.calls == []
    assert runner.prepared == []


def test_a_phase_override_that_names_no_field_is_refused_with_its_path(
    tmp_path, monkeypatch
) -> None:
    """A dotted override is checked at every segment, not only at its leaf.

    The configuration below has a ``flow`` and no ``flowx``, so the answer is
    known before the writer runs. A non-leaf typo used to leave the runner as
    a bare ``AttributeError``, which the CLI has no code for.
    """
    from pydantic import BaseModel, ConfigDict

    from hydromodpy.calibration.runners import trial as trial_module

    class Flow(BaseModel):
        model_config = ConfigDict(extra="forbid")
        flow_regime: str = "steady"

    class Root(BaseModel):
        model_config = ConfigDict(extra="forbid")
        flow: Flow = Flow()

    monkeypatch.setattr(
        trial_module,
        "get_root_config_provider",
        lambda: SimpleNamespace(from_toml=lambda path: Root()),
    )
    cfg_path = tmp_path / "project.toml"
    cfg_path.write_text('[simulation]\nname = "toy"\n', encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=r"flowx\.flow_regime"):
        trial_module.prepare_trials(
            cfg_path,
            override_paths={"K": "flow.flow_regime"},
            config_overrides={"flowx.flow_regime": "transient"},
        )


def test_a_refused_preparation_is_reported_with_the_phase_that_asked_for_it(
    tmp_path, monkeypatch
) -> None:
    """The preparation does not know which phase asked; the runner does.

    A staged calibration prepares once per phase, so a refusal that names only
    the path leaves the reader to guess which of the declared phases owns it.
    """

    def refuse(*args, **kwargs):
        raise ConfigValidationError("config override 'flowx.flow_regime' cannot be written")

    monkeypatch.setattr(staged_runner, "prepare_trials", refuse)

    with pytest.raises(ConfigValidationError) as refusal:
        run_staged_calibration(_write(tmp_path))

    message = str(refusal.value)
    assert "steady_k" in message
    assert "flowx.flow_regime" in message


# -- return shape ------------------------------------------------------------


def test_the_runner_can_return_the_payload_instead_of_the_report(tmp_path, runner) -> None:
    """``Project.calibrate`` documents ``return_report`` for every mode."""
    payload = run_staged_calibration(_write(tmp_path), return_report=False)

    assert isinstance(payload, dict)
    assert [item["phase"] for item in payload["phases"]] == ["steady_k", "transient_sy"]
    assert payload["root_session_id"] == payload["phases"][0]["session_id"]


# -- session chain -----------------------------------------------------------


def test_the_chain_links_each_phase_to_the_previous_one(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    first, second = (call.chain for call in runner.calls)
    assert first.parent_session_id is None
    assert first.root_session_id == first.session_id
    assert second.parent_session_id == first.session_id
    assert second.root_session_id == first.session_id
    assert first.session_id != second.session_id
    assert (first.phase_index, second.phase_index) == (0, 1)
    assert (first.phase_name, second.phase_name) == ("steady_k", "transient_sy")


def test_the_report_carries_the_chain_of_the_run(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert report.root_session_id == report.phases[0].session_id
    assert report.phases[0].parent_session_id is None
    assert report.phases[1].parent_session_id == report.phases[0].session_id
    assert report.phases[1].root_session_id == report.root_session_id


def test_a_single_selected_phase_is_the_root_of_its_own_chain(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path), phase="steady_k")

    chain = runner.calls[0].chain
    assert chain.parent_session_id is None
    assert chain.root_session_id == chain.session_id == report.root_session_id


# -- restart-based uncertainty ------------------------------------------------

MULTISTART = """
[calibration.uncertainty]
method = "multistart"
restarts = 3
"""

NELDER_PHASES = """
[[calibration.phases]]
name = "steady_k"
method = "scipy_nelder_mead"
max_iter = 12
parameters = ["K"]
objective_blocks = ["q_block"]
outputs = ["q"]
"""


def _write_multistart(tmp_path: Path) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + MULTISTART + NELDER_PHASES, encoding="utf-8")
    return path


def test_without_restarts_one_phase_is_one_search(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    assert len(runner.calls) == 2
    assert all(call.start_at is None for call in runner.calls)


def test_restarts_run_the_phase_that_many_times(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_multistart(tmp_path))

    assert len(runner.calls) == 3
    assert [phase.name for phase in report.phases] == ["steady_k"]


def test_the_first_restart_is_the_search_that_would_have_run_alone(tmp_path, runner) -> None:
    # The answer a file already published stays in the set: the engine keeps its
    # own start and the declared seed for restart one.
    run_staged_calibration(_write_multistart(tmp_path))

    assert runner.calls[0].start_at is None
    assert all(call.start_at is not None for call in runner.calls[1:])


def test_each_restart_carries_its_own_seed(tmp_path, runner) -> None:
    run_staged_calibration(_write_multistart(tmp_path))

    assert len({call.seed for call in runner.calls}) == 3


def test_the_report_publishes_the_spread_beside_the_value(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_multistart(tmp_path))

    spread = {item.parameter: item for item in report.restart_spreads}
    assert "K" in spread
    # The fake returns the same optimum every time, so the spread is degenerate
    # and says so rather than inventing a width.
    assert spread["K"].lowest == pytest.approx(spread["K"].highest)
    assert spread["K"].best == pytest.approx(spread["K"].lowest)
    assert report.to_dict()["restart_spreads"][0]["n_restarts"] == 3


def test_restarts_on_an_exhaustive_sweep_are_refused(tmp_path, runner) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + MULTISTART + TWO_PHASES, encoding="utf-8")

    with pytest.raises(ValueError, match="same answer every time"):
        run_staged_calibration(path)


# -- linearized uncertainty ---------------------------------------------------

LINEARIZED = """
[calibration.uncertainty]
method = "linearized"
perturbation = 0.01
"""


def _write_linearized(tmp_path: Path, phases: str = TWO_PHASES) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + LINEARIZED + phases, encoding="utf-8")
    return path


class FakeWidth:
    """Stands in for the model rebuild a linearized width would run.

    The real ``attach_a_linearized_width`` perturbs each parameter and reruns
    the model; what is under test here is that staged_runner calls it once per
    phase, with that phase's own configuration, not whether the derivative
    itself is right (covered where the real function is tested).
    """

    def __init__(self) -> None:
        self.calls: list[SimpleNamespace] = []

    def __call__(self, report, *, cfg, trial_ctx, space, perturbation):
        self.calls.append(
            SimpleNamespace(
                report=report, cfg=cfg, trial_ctx=trial_ctx, space=space, perturbation=perturbation
            )
        )
        widened = SimpleNamespace(name=next(iter(cfg.parameters)))
        return replace(report, parameter_uncertainty=(widened,))


@pytest.fixture
def width(monkeypatch) -> FakeWidth:
    fake = FakeWidth()
    monkeypatch.setattr(staged_runner, "attach_a_linearized_width", fake)
    return fake


def test_linearized_uncertainty_attaches_a_width_to_each_phase(tmp_path, runner, width) -> None:
    report = run_staged_calibration(_write_linearized(tmp_path))

    assert len(width.calls) == 2
    assert all(phase.report.parameter_uncertainty for phase in report.phases)


def test_linearized_uncertainty_reads_the_phase_that_scored_it(tmp_path, runner, width) -> None:
    # steady_k scores q_block/q, transient_sy scores h_block/h: the width has
    # to be taken through the phase's own configuration, not the document's.
    run_staged_calibration(_write_linearized(tmp_path))

    steady, transient = width.calls
    assert list(steady.cfg.outputs) == ["q"]
    assert list(transient.cfg.outputs) == ["h"]
    assert next(iter(steady.cfg.parameters)) == "K"
    assert next(iter(transient.cfg.parameters)) == "Sy"


def test_a_width_conditional_on_an_earlier_freeze_says_so(tmp_path, runner, width) -> None:
    # transient_sy depends_on steady_k and steady_k freezes K by default: the
    # second phase's width is conditional on a value it did not calibrate.
    report = run_staged_calibration(_write_linearized(tmp_path))

    steady, transient = report.phases
    assert "parameter_uncertainty_note" not in steady.report.extra
    assert "K" in transient.report.extra["parameter_uncertainty_note"]


# A phase without an evaluator that prepares a model never reaches
# ``_attach_linearized_width`` with ``trial_ctx=None``: ``run_staged_calibration``
# already refuses that evaluator up front, with a more precise message, and
# ``prepare_trials`` never returns ``None``. A second, less precise refusal
# behind it would be dead code reachable only by calling the private helper
# directly, which is what such a test would do -- covered instead below by
# giving the same evaluator to the public entry point.
def test_an_evaluator_that_prepares_no_model_is_refused_before_any_phase_solves(
    tmp_path, monkeypatch
) -> None:
    # The refusal itself predates this phase. What is asserted here is that it
    # still comes FIRST: an evaluator that prepares no model is turned away
    # before any phase runs, so the linearized width this document asks for is
    # never reached. Counting the calls is what makes the test fail if the
    # width dispatch is ever moved ahead of the refusal.
    calls: list[str] = []
    monkeypatch.setattr(
        staged_runner,
        "attach_a_linearized_width",
        lambda *args, **kwargs: calls.append("called"),
    )
    path = tmp_path / "calibration.toml"
    path.write_text(
        BASE.replace('method = "grid"', 'method = "grid"\nevaluator = "analytic_bowl"', 1)
        + LINEARIZED
        + TWO_PHASES,
        encoding="utf-8",
    )

    with pytest.raises(CalibrationError, match="runs no HydroModPy model"):
        run_staged_calibration(path)

    assert calls == []


def test_a_single_metric_phase_keeps_its_report_and_names_why_no_width_is_attached(
    tmp_path, runner, monkeypatch
) -> None:
    # Single-metric route: no residual vector, structurally, so the width is
    # skipped before ``attach_a_linearized_width`` is even called -- cheap
    # enough to exercise the real ``_attach_linearized_width``, not a double.
    #
    # ``staged_runner.logger`` is patched directly rather than read through
    # ``caplog``: its underlying "hydromodpy" logger has ``propagate`` turned
    # off the moment anything in the process builds a ``LogManager``, which
    # would silently blind a root-attached capture handler.
    warnings: list[str] = []
    monkeypatch.setattr(
        staged_runner.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    single_metric = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
variable = "discharge"
objective = "nse"
"""
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + LINEARIZED + single_metric, encoding="utf-8")

    report = run_staged_calibration(path)

    (steady,) = report.phases
    assert not steady.report.parameter_uncertainty
    text = " ".join(warnings)
    assert "steady_k" in text
    assert "no linearized width is attached" in text


def test_a_phase_scoring_only_a_network_output_keeps_its_report(
    tmp_path, runner, monkeypatch
) -> None:
    # The regression this guard exists for, and the one that cost a whole
    # staged run. ``CalibOutputNetwork`` carries no ``observes`` field at all
    # -- the loader refuses one -- so a phase scored on it holds an output,
    # holds no station, and can never hold one. A guard reading
    # ``bool(phase_cfg.outputs)`` called the real width builder anyway, which
    # raised on the empty residual vector and killed the run AFTER the search
    # had been paid for. It is the shape of the only registered protocol:
    # ``matching_hydrographic_network`` scores its steady stage exactly here.
    warnings: list[str] = []
    monkeypatch.setattr(
        staged_runner.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    network = """
[calibration.outputs.net]
support = "network"
observed_network = "data.hydrography"

[[calibration.objective_blocks]]
name = "net_block"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
objective_blocks = ["net_block"]
"""
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + LINEARIZED + network, encoding="utf-8")

    report = run_staged_calibration(path)

    (steady,) = report.phases
    assert not steady.report.parameter_uncertainty
    assert "can name a station" in steady.report.extra["parameter_uncertainty_absent_note"]
    text = " ".join(warnings)
    assert "steady_k" in text
    assert "no linearized width is attached" in text


def test_a_phase_reused_from_disk_gets_a_note_instead_of_a_recomputed_width(
    tmp_path, runner, width, monkeypatch
) -> None:
    # A reused phase must not recompute a width -- that would rerun the model
    # on a path written precisely to avoid it -- but the absence has to be said,
    # not merely left silent.
    #
    # steady_k's stub freeze is NOT empty: an empty one would make the
    # transient phase's "conditional on a freeze" note fire for free, whether
    # or not the reuse branch is wired correctly, because ``frozen`` would
    # stay empty either way.
    disk_report = CalibrationReport(
        session_id="disk-session",
        method="bisection",
        n_iterations=1,
        best_objective=0.1,
        best_sim_id=None,
        duration_s=0.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": K_CALIBRATED},
        workspace=tmp_path,
        extra={"reused_from_disk": True, "source_root_session_id": "root"},
    )
    path = tmp_path / "calibration.toml"
    path.write_text(
        BASE.replace('method = "grid"', 'method = "grid"\nreuse_completed_phases = true', 1)
        + LINEARIZED
        + TWO_PHASES,
        encoding="utf-8",
    )
    cfg, _raw = staged_runner.load_toml_calibration(path)
    declared = staged_runner.space_from_config(cfg)
    steady_froze = (
        staged_runner.FrozenParameter(
            parameter=declared["K"], value=K_CALIBRATED, phase="steady_k"
        ),
    )
    monkeypatch.setattr(
        staged_runner,
        "_reuse_from_disk",
        lambda **kwargs: (disk_report, steady_froze) if kwargs["decl"].name == "steady_k" else None,
    )

    report = run_staged_calibration(path, resume_root_session_id="root")

    steady, transient = report.phases
    # Reused phases must not pay for a recomputed width: only transient_sy,
    # which actually solved, may have called it.
    assert len(width.calls) == 1
    assert next(iter(width.calls[0].cfg.parameters)) == "Sy"
    assert "reused from a previous run" in steady.report.extra["parameter_uncertainty_absent_note"]
    assert transient.report.extra.get("parameter_uncertainty_absent_note") is None
    # The freeze IS non-empty this time, so this now measures the real thing:
    # transient_sy's width is conditional on the K reused from disk.
    assert "K" in transient.report.extra["parameter_uncertainty_note"]


def test_a_reused_single_metric_phase_gets_the_structural_note_not_the_reuse_one(
    tmp_path, runner, width, monkeypatch
) -> None:
    # steady_k is single-metric here: its phase_cfg carries no outputs at all
    # (_phase_config empties them), reused or not. The reuse note would blame
    # the wrong cause; the note has to name the true, structural one instead.
    disk_report = CalibrationReport(
        session_id="disk-session",
        method="bisection",
        n_iterations=1,
        best_objective=0.1,
        best_sim_id=None,
        duration_s=0.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": K_CALIBRATED},
        workspace=tmp_path,
        extra={"reused_from_disk": True, "source_root_session_id": "root"},
    )
    monkeypatch.setattr(
        staged_runner,
        "_reuse_from_disk",
        lambda **kwargs: (disk_report, ()) if kwargs["decl"].name == "steady_k" else None,
    )
    single_metric_first = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
variable = "discharge"
objective = "nse"

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy"]
objective_blocks = ["h_block"]
depends_on = "steady_k"
"""
    path = tmp_path / "calibration.toml"
    path.write_text(
        BASE.replace('method = "grid"', 'method = "grid"\nreuse_completed_phases = true', 1)
        + LINEARIZED
        + single_metric_first,
        encoding="utf-8",
    )
    report = run_staged_calibration(path, resume_root_session_id="root")

    steady, _transient = report.phases
    note = steady.report.extra["parameter_uncertainty_absent_note"]
    assert "reused from a previous run" not in note
    assert "can name a station" in note
    assert "no residual vector" in note
