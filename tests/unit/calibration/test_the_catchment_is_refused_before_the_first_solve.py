"""A scored catchment that is not the delineated one is refused before the first solve.

``catchment_mismatch`` depends on the geometry alone, so one build answers for every
trial. It replaces a bound on a share that is zero by construction: the outlet is
sealed into the target of ``D_so``, so every cell of the catchment reaches it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputNetwork, CalibrationConfig
from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners import prepared_model, trial
from hydromodpy.calibration.runners.prepared_model import (
    _assert_the_scored_catchment_is_the_delineated_one as veto,
)
from hydromodpy.calibration.runners.trial import TrialContext, built_model, prepare_trials
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.solver.base.adapter_protocol import STOP_BEFORE_THE_SOLVE
from hydromodpy.solver.modflow_common.flow_adapter_helpers import run_flow_model

MAP = {"support": "network", "stream_geometry_path": "map.gpkg"}


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


def _trial_ctx() -> TrialContext:
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
            veto(_cfg(), _trial_ctx(), _space())

        assert built.builds == 1

    def test_a_gap_under_the_bound_says_so_and_passes(self, built, caplog) -> None:
        built.gap = 0.04

        with caplog.at_level(logging.INFO):
            veto(_cfg(), _trial_ctx(), _space())

        assert "catchment_mismatch = 4.00%" in caplog.text

    def test_a_synthetic_domain_has_no_gap_to_refuse(self, built) -> None:
        built.gap = float("nan")

        veto(_cfg(), _trial_ctx(), _space())

    def test_a_larger_bound_lets_the_gap_through(self, built) -> None:
        built.gap = 0.11

        veto(_cfg(verdict={"max_catchment_mismatch": 0.2}), _trial_ctx(), _space())

    def test_false_builds_nothing_and_refuses_nothing(self, built) -> None:
        built.gap = 0.9

        veto(_cfg(verdict={"max_catchment_mismatch": False}), _trial_ctx(), _space())

        assert built.builds == 0

    def test_a_search_on_no_network_builds_nothing(self, built) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {"q": {"support": "point", "variable": "discharge", "observes": "S"}},
                "objective_blocks": [{"name": "q", "metric": "nse", "uses_outputs": ["q"]}],
            }
        )

        veto(cfg, _trial_ctx(), _space())

        assert built.builds == 0

    def test_it_runs_with_the_other_checks_of_the_prepared_model(self, built, monkeypatch) -> None:
        built.gap = 0.5
        monkeypatch.setattr(prepared_model, "_assert_bounds_valid", lambda *a: None)

        with pytest.raises(ObjectiveError, match="catchment_mismatch"):
            prepared_model.check_the_prepared_model(_cfg(), _trial_ctx(), _space())


class TestTheKeys:
    def test_the_old_bound_is_refused_with_the_key_that_replaces_it(self) -> None:
        with pytest.raises(ValidationError, match=r"verdict\] max_catchment_mismatch"):
            CalibOutputNetwork(stream_geometry_path="map.gpkg", max_unreachable_fraction=0.05)

    def test_true_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="write a share"):
            CalibOutputNetwork(
                stream_geometry_path="map.gpkg", verdict={"max_catchment_mismatch": True}
            )

    def test_a_negative_share_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CalibOutputNetwork(
                stream_geometry_path="map.gpkg", verdict={"max_catchment_mismatch": -0.1}
            )

    def test_false_survives_a_dump(self) -> None:
        output = CalibOutputNetwork(
            stream_geometry_path="map.gpkg", verdict={"max_catchment_mismatch": False}
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
        model = SimpleNamespace(
            pre_processing=lambda **kwargs: calls.append("pre"),
            processing=lambda **kwargs: calls.append("solve"),
        )
        setup = SimpleNamespace(
            flow=None,
            domain=None,
            cell_mesh=object(),
            flow_runtime_overrides={STOP_BEFORE_THE_SOLVE: True},
        )

        result = run_flow_model(SimpleNamespace(state=SimpleNamespace(setup=setup)), model, None)

        assert calls == ["pre"]
        assert result.primary_model is model

    def test_a_real_preparation_builds_the_model_and_sweeps_its_folder(
        self, tmp_path, monkeypatch
    ) -> None:
        from hydromodpy.solver.modflow6.modflow6 import Modflow6

        def no_solve(self, *args, **kwargs):
            raise AssertionError("the model was to be built, not solved")

        monkeypatch.setattr(Modflow6, "processing", no_solve)
        path = tmp_path / "project.toml"
        path.write_text(PROJECT_TOML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        trial_ctx = prepare_trials(
            path, override_paths={"K": "flow.param.K.field.value"}, parameter_space=_space()
        )

        with built_model(trial_ctx, {"K": 1e-5}) as ctx:
            _, run_ctx = solver_extract.resolve_flow_adapter(ctx)
            assert int(run_ctx.model.solver_mesh.n_cells) == 400
            assert np.isfinite(np.asarray(run_ctx.model.solver_mesh.top, dtype=float)).all()
            folder = Path(run_ctx.model.full_path)

        assert not folder.exists()
