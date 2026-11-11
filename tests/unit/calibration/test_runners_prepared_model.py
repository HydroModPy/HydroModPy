"""Tests of `runners.prepared_model`."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners import prepared_model, trial
from hydromodpy.calibration.runners.prepared_model import (
    _assert_active_release_packages_follow_k,
    _assert_bounds_valid,
    _assert_network_conductance_proportional,
)
from hydromodpy.calibration.runners.prepared_model import (
    _assert_the_scored_catchment_is_the_delineated_one as veto,
)
from hydromodpy.calibration.runners.trial import TrialContext, built_model, prepare_trials
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.base.runner import solve_one
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.flow_run import (
    build_flow_model,
    build_preprocess_options,
    run_flow_model,
)
from tests._helpers.model_factory import make_model

# From test_bounds_preflight.py
# Pre-flight refusals the calibration runner makes before the first solve.
#
# Two of them. A calibration bound outside what the target field accepts (e.g. a
# specific yield below its physical floor) is silent until each trial that samples
# there crashes at fork, so the runner probes every bound by rebuilding the flow
# once. And a stream-network criterion whose drain conductance is fixed rather
# than proportional to the conductivity runs to the end and returns a ratio that
# means nothing, so the runner refuses it up front.


_FLOOR = 1e-4


class _Flow:
    """Probe flow carrying the injected parameter value."""

    value: float | None = None


class _Cfg:
    """Config double exposing the ``flow`` + ``model_copy`` contract used by the probe."""

    def __init__(self) -> None:
        self.flow = _Flow()

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        clone = _Cfg()
        clone.flow = _Flow()
        return clone


def _param(name, lower, upper, path="flow.param.Sy.field.value", mode="replace"):
    return SimpleNamespace(name=name, lower=lower, upper=upper, effective_path=path, mode=mode)


def _trial_ctx() -> SimpleNamespace:
    return SimpleNamespace(base_cfg=_Cfg())


@pytest.fixture()
def _floor_flow(monkeypatch):
    """Build a fake flow that rejects an injected value below the floor."""

    def fake_apply(cfg, param, value):
        cfg.flow.value = value

    def fake_flow(*, config):
        v = getattr(config, "value", None)
        if v is not None and v < _FLOOR:
            raise ValueError(f"specific yield value {v} outside [0.0001, 0.5]")
        return object()

    monkeypatch.setattr(
        "hydromodpy.calibration.optim.parameters.apply_parameter_to_config", fake_apply
    )
    monkeypatch.setattr("hydromodpy.model.flow.Flow", fake_flow)


@pytest.mark.fast
def test_rejects_lower_bound_below_field_floor(_floor_flow):
    space = [_param("Sy", 1e-7, 1e-1)]
    with pytest.raises(ValueError, match=r"'Sy'.*lower bound.*outside the valid range"):
        _assert_bounds_valid(_trial_ctx(), space)


@pytest.mark.fast
@pytest.mark.parametrize(
    "space",
    [
        pytest.param(
            [_param("Sy", 1e-4, 1e-1), _param("K", 1e-3, 1.0, path="flow.param.K.field.value")],
            id="bounds_within_the_field_range",
        ),
        pytest.param([_param("free", 1e-9, 1.0, path=None)], id="params_without_path_are_skipped"),
        # A non-flow target is not covered by the flow rebuild probe.
        pytest.param(
            [_param("alpha", 1e-9, 1.0, path="transport.param.alpha")], id="non_flow_params_skipped"
        ),
    ],
)
def test_bounds_the_probe_accepts_or_skips_raise_nothing(_floor_flow, space):
    _assert_bounds_valid(_trial_ctx(), space)


@pytest.mark.fast
def test_missing_cfg_is_noop():
    _assert_bounds_valid(SimpleNamespace(base_cfg=None), [])


def _network_cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "outputs": {"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
            "objective_blocks": [
                {"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def _moving(*, moves_k: bool) -> list[SimpleNamespace]:
    path = "flow.param.K.field.value" if moves_k else "flow.param.Sy.field.value"
    return [_param("K" if moves_k else "Sy", 1e-7, 1e-3, path=path)]


def _single_metric_cfg(objective: str = "distance_gap") -> CalibrationConfig:
    """A phase config the way ``staged_runner._phase_config`` narrows it.

    A single-metric phase loses its ``outputs`` and ``objective_blocks``, so the
    guards see only its ``variable`` and ``objective``.
    """
    return CalibrationConfig.model_validate(
        {"method": "grid", "variable": "net", "objective": objective}
    )


@pytest.mark.fast
class TestDrainConductanceIsProportional:
    """A network criterion needs the drain conductance to follow the conductivity.

    ``C = K * cell_area / drain_bed_thickness_m`` is what makes K/R the
    calibrated quantity. Both MODFLOW backends and Boussinesq apply it only
    when the configured conductance is not strictly positive, so a fixed
    value in ``[flow.bc.drainage] kind = "drain"`` silently costs the
    criterion its invariance.
    """

    @staticmethod
    def _flow(value: float | None, *, kind: str = "drain", active: bool = True):
        payload: dict[str, object] = {}
        if value is not None:
            payload["bc"] = {"drainage": {"kind": kind, "value": value, "enabled": active}}
        elif active:
            payload["bc"] = {"drainage": {}}
        return FlowConfig.model_validate(payload)

    def _check(self, flow, cfg, *, moves_k: bool = True) -> None:
        _assert_network_conductance_proportional(
            cfg,
            SimpleNamespace(base_cfg=SimpleNamespace(flow=flow)),
            _moving(moves_k=moves_k),
        )

    def test_a_fixed_conductance_is_refused_when_the_search_moves_k(self) -> None:
        with pytest.raises(ObjectiveError) as excinfo:
            self._check(self._flow(1e-3), _network_cfg())
        message = str(excinfo.value)
        assert "flow.bc.drainage.value" in message
        assert "0.001" in message
        assert "'net'" in message
        assert "drain_bed_thickness_m" in message
        assert "top_thickness" not in message

    def test_a_fixed_conductance_is_only_a_warning_when_k_does_not_move(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            self._check(self._flow(1e-3), _network_cfg(), moves_k=False)  # no raise
        assert any(
            "does not move a hydraulic conductivity" in rec.message for rec in caplog.records
        )

    def test_a_drain_is_named_by_its_own_family(self) -> None:
        with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
            self._check(self._flow(2.0, kind="drain"), _network_cfg())

    def test_a_fixed_conductance_is_refused_on_a_single_metric_network_phase(self) -> None:
        with pytest.raises(ObjectiveError) as excinfo:
            self._check(self._flow(1e-3), _single_metric_cfg())
        assert "'net'" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("value", "options", "cfg"),
        [
            pytest.param(0.0, {}, _network_cfg, id="the_proportional_fallback"),
            # Nothing declares a conductance, so nothing overrides the fallback.
            pytest.param(None, {}, _network_cfg, id="an_active_boundary_without_a_section"),
            pytest.param(1e-3, {"active": False}, _network_cfg, id="an_inactive_drainage"),
            pytest.param(
                1e-3,
                {},
                lambda: CalibrationConfig.model_validate({"method": "grid", "variable": "head"}),
                id="a_calibration_without_a_network_output",
            ),
        ],
    )
    def test_these_conductances_pass(self, value, options, cfg) -> None:
        self._check(self._flow(value, **options), cfg())


@pytest.mark.fast
class TestReleasePackagesFollowK:
    """SFR and LAK build their own conductance, never derived from K.

    A K-moving network search next to one of them is refused before the first
    solve, the same way a fixed drain conductance is; DRN and CHD are fine.
    """

    @staticmethod
    def _flow(active_bc: list[str]):
        tables = {
            "sfr": {"sinks_sources": {"sfr": {"main": {}}}},
            "lake": {"sinks_sources": {"lakes": {"l1": {"bedleak": 1.0, "initial_stage": 1.0}}}},
            "drainage": {"bc": {"drainage": {}}},
            "west_side": {"bc": {"west_side": {"kind": "dirichlet"}}},
        }
        payload: dict[str, dict] = {}
        for name in active_bc:
            for section, content in tables[name].items():
                payload.setdefault(section, {}).update(content)
        return FlowConfig.model_validate(payload)

    def _check(self, active_bc: list[str], *, moves_k: bool = True, cfg=None) -> None:
        _assert_active_release_packages_follow_k(
            _network_cfg() if cfg is None else cfg,
            SimpleNamespace(base_cfg=SimpleNamespace(flow=self._flow(active_bc))),
            _moving(moves_k=moves_k),
        )

    def test_a_single_metric_network_phase_next_to_an_sfr_is_refused(self) -> None:
        with pytest.raises(ObjectiveError) as excinfo:
            self._check(["sfr"], cfg=_single_metric_cfg())
        assert "'net'" in str(excinfo.value)

    def test_an_active_sfr_is_refused_when_the_search_moves_k(self) -> None:
        with pytest.raises(ObjectiveError) as excinfo:
            self._check(["sfr"])
        message = str(excinfo.value)
        assert "SFR" in message
        assert "future work" in message

    def test_an_active_lake_is_refused_when_the_search_moves_k(self) -> None:
        with pytest.raises(ObjectiveError, match="LAK"):
            self._check(["lake"])

    @pytest.mark.parametrize(
        ("active_bc", "options"),
        [
            pytest.param(["sfr"], {"cfg": _single_metric_cfg("nse")}, id="a_non_network_metric"),
            pytest.param(["sfr"], {"moves_k": False}, id="sfr_when_k_does_not_move"),
            # DRN's conductance follows K, and CHD fixes a head.
            pytest.param(["drainage"], {}, id="drainage_alone"),
            pytest.param(["west_side"], {}, id="a_side_chd_alone"),
        ],
    )
    def test_these_release_packages_pass(self, active_bc, options) -> None:
        self._check(active_bc, **options)


# From test_the_catchment_is_refused_before_the_first_solve.py
# A scored catchment that is not the delineated one is refused before the first solve.
#
# ``catchment_mismatch`` depends on the geometry alone, so one build answers for every
# trial. It replaces a bound on a share that is zero by construction: the outlet is
# sealed into the target of ``D_so``, so every cell of the catchment reaches it.


MAP = {"support": "network", "map": {"complete": "map.gpkg"}}


def _cfg(**output) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
            "outputs": {"net": {**MAP, **output}},
            "objective_blocks": [
                {"name": "net", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def _space() -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}
    )


@pytest.fixture
def built(monkeypatch):
    """Serve a built model and a geometry whose gap the test sets."""
    seen = SimpleNamespace(builds=0, gap=0.0)

    class _Built:
        def __enter__(self):
            seen.builds += 1
            return SimpleNamespace()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(trial, "built_model", lambda *a, **k: _Built())
    monkeypatch.setattr(
        solver_extract, "resolve_flow_adapter", lambda ctx: (object(), SimpleNamespace())
    )
    monkeypatch.setattr(solver_extract, "scored_catchment_mismatch", lambda *a: seen.gap)
    return seen


def _trial_ctx__catchment_refused() -> TrialContext:
    return TrialContext(
        base_cfg=None,
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths={},
        workspace=Path("."),
        cfg_path=Path("x.toml"),
    )


class TestTheVeto:
    def test_a_gap_above_the_bound_is_refused_with_its_share(self, built) -> None:
        built.gap = 0.11

        with pytest.raises(ObjectiveError, match=r"catchment_mismatch = 11\.0%.*5\.0% bound"):
            veto(_cfg(), _trial_ctx__catchment_refused(), _space())

        assert built.builds == 1

    def test_a_gap_under_the_bound_says_so_and_passes(self, built, caplog) -> None:
        built.gap = 0.04

        with caplog.at_level(logging.INFO):
            veto(_cfg(), _trial_ctx__catchment_refused(), _space())

        assert "catchment_mismatch = 4.00%" in caplog.text

    def test_a_synthetic_domain_has_no_gap_to_refuse(self, built) -> None:
        built.gap = float("nan")

        veto(_cfg(), _trial_ctx__catchment_refused(), _space())

    def test_a_larger_bound_lets_the_gap_through(self, built) -> None:
        built.gap = 0.11

        veto(
            _cfg(verdict={"max_catchment_mismatch": 0.2}), _trial_ctx__catchment_refused(), _space()
        )

    def test_false_builds_nothing_and_refuses_nothing(self, built) -> None:
        built.gap = 0.9

        veto(
            _cfg(verdict={"max_catchment_mismatch": False}),
            _trial_ctx__catchment_refused(),
            _space(),
        )

        assert built.builds == 0

    def test_a_search_on_no_network_builds_nothing(self, built) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {"q": {"support": "point", "variable": "discharge", "observes": "S"}},
                "objective_blocks": [{"name": "q", "metric": "nse", "uses_outputs": ["q"]}],
            }
        )

        veto(cfg, _trial_ctx__catchment_refused(), _space())

        assert built.builds == 0

    def test_it_runs_with_the_other_checks_of_the_prepared_model(self, built, monkeypatch) -> None:
        built.gap = 0.5
        monkeypatch.setattr(prepared_model, "_assert_bounds_valid", lambda *a: None)

        with pytest.raises(ObjectiveError, match="catchment_mismatch"):
            prepared_model.check_the_prepared_model(
                _cfg(), _trial_ctx__catchment_refused(), _space()
            )


class TestTheKeys:
    def test_the_old_bound_is_refused_with_the_key_that_replaces_it(self) -> None:
        with pytest.raises(ValidationError, match=r"verdict\] max_catchment_mismatch"):
            CalibOutputNetwork(map={"complete": "map.gpkg"}, max_unreachable_fraction=0.05)

    def test_true_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="write a share"):
            CalibOutputNetwork(
                map={"complete": "map.gpkg"}, verdict={"max_catchment_mismatch": True}
            )

    def test_a_negative_share_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CalibOutputNetwork(
                map={"complete": "map.gpkg"}, verdict={"max_catchment_mismatch": -0.1}
            )

    def test_false_survives_a_dump(self) -> None:
        output = CalibOutputNetwork(
            map={"complete": "map.gpkg"}, verdict={"max_catchment_mismatch": False}
        )

        reloaded = CalibOutputNetwork.model_validate(output.model_dump(mode="json"))

        assert reloaded.verdict.max_catchment_mismatch is False


PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "built"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["modflow6"]

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "built"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "30 m"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[display]
enabled = false
"""


class TestTheModelIsBuiltAndNotSolved:
    def test_the_run_stops_after_the_preprocessing(self) -> None:
        calls: list[str] = []
        solver_model = SimpleNamespace(
            pre_processing=lambda *args, **kwargs: calls.append("pre"),
            processing=lambda **kwargs: calls.append("solve"),
        )
        adapter = SimpleNamespace(
            validate=lambda *args: None,
            build=lambda model, options, slot, upstream=(): build_flow_model(
                solver_model, model, options, slot, build_preprocess_options(model)
            ),
            run=lambda solver_run: run_flow_model(solver_run, solver_name="modflow6"),
        )
        slot = RunSlot(Path("unused"), "island", stop_before_solve=True)

        result = solve_one(adapter, make_model(), None, slot, upstream=())

        assert calls == ["pre"]
        assert result.solver_model is solver_model
        assert not result.solved

    @pytest.mark.parametrize(
        "override_paths",
        [{"K": "flow.param.K.field.value"}, ["flow.param.K.field.value"]],
        ids=["by_name", "by_path"],
    )
    def test_a_real_preparation_builds_the_model_and_sweeps_its_folder(
        self, tmp_path, monkeypatch, override_paths
    ) -> None:
        def no_solve(self, *args, **kwargs):
            raise AssertionError("the model was to be built, not solved")

        monkeypatch.setattr(Modflow6, "processing", no_solve)
        path = tmp_path / "project.toml"
        path.write_text(PROJECT_TOML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        trial_ctx = prepare_trials(path, override_paths=override_paths, parameter_space=_space())

        with built_model(trial_ctx, {"K": 1e-5}) as ctx:
            _, run_ctx = solver_extract.resolve_flow_adapter(ctx)
            assert int(run_ctx.solver_run.solver_model.solver_mesh.n_cells) == 400
            assert np.isfinite(
                np.asarray(run_ctx.solver_run.solver_model.solver_mesh.top, dtype=float)
            ).all()
            folder = Path(run_ctx.solver_run.solver_model.full_path)

        assert not folder.exists()
