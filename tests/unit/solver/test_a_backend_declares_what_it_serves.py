"""Whether a backend can serve an observable is not a property of its class.

MODFLOW 6 hands back a lake stage, but only when the file declares a lake.
MODFLOW-NWT never can, because it builds no LAK package at all. Collapsing those
two into one "no" tells a user to change backend when they only had to declare a
lake; collapsing them into "yes" postpones the refusal to the first extraction,
hours into a search.

So each flow backend answers on the RESOLVED configuration, in three states, and
the third one carries the sentence saying what to declare.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.base.observable_support import ObservableSupport
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _config(tmp_path, backend: str, **flow: object):
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.solver.base.solver_config import SolverConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        solver=SolverConfig(backend={"backend": backend}),
        flow=FlowConfig(**flow),
    )


def _declared(backend: str, cfg) -> dict[str, ObservableSupport]:
    import importlib

    module, cls = {
        "modflow6": ("hydromodpy.solver.modflow6.adapters.flow", "Modflow6FlowAdapter"),
        "modflow_nwt": ("hydromodpy.solver.modflow_nwt.adapters.flow", "ModflowNwtFlowAdapter"),
        "boussinesq": ("hydromodpy.solver.boussinesq.adapters.flow", "BoussinesqFlowAdapter"),
    }[backend]
    adapter = getattr(importlib.import_module(module), cls)()
    return {item.name: item for item in adapter.declared_observables(cfg)}


@pytest.mark.parametrize("backend", ["modflow6", "modflow_nwt", "boussinesq"])
def test_every_flow_backend_answers(tmp_path, backend: str) -> None:
    declared = _declared(backend, _config(tmp_path, backend))

    assert declared, backend


@pytest.mark.parametrize("backend", ["modflow6", "modflow_nwt", "boussinesq"])
def test_every_backend_serves_a_head_at_a_cell(tmp_path, backend: str) -> None:
    """The one observable all three have always produced."""
    declared = _declared(backend, _config(tmp_path, backend))

    assert declared["head"].is_servable_now, declared["head"].reason


class TestTheThirdState:
    def test_a_lake_stage_waits_on_a_declaration_under_modflow6(self, tmp_path) -> None:
        declared = _declared("modflow6", _config(tmp_path, "modflow6"))

        assert declared["stage"].state == "servable_under_condition"
        assert "active_bc" in declared["stage"].reason

    def test_declaring_the_lake_makes_it_servable(self, tmp_path) -> None:
        declared = _declared("modflow6", _config(tmp_path, "modflow6", active_bc=["lake"]))

        assert declared["stage"].is_servable_now

    def test_a_lake_stage_is_never_servable_under_nwt(self, tmp_path) -> None:
        declared = _declared("modflow_nwt", _config(tmp_path, "modflow_nwt"))

        assert declared["stage"].can_never_be_served
        assert "LAK" in declared["stage"].reason

    def test_declaring_a_lake_does_not_make_nwt_serve_it(self, tmp_path) -> None:
        """No configuration changes what a backend does not build."""
        with pytest.raises(Exception):
            _config(tmp_path, "modflow_nwt", active_bc=["lake"])


class TestTheNetworkCriterionsInput:
    def test_modflow6_serves_the_release_flux(self, tmp_path) -> None:
        declared = _declared("modflow6", _config(tmp_path, "modflow6"))

        assert declared["release_flux"].is_servable_now

    def test_boussinesq_serves_it_too(self, tmp_path) -> None:
        """It computes a saturation excess per cell, so the criterion is reachable."""
        declared = _declared("boussinesq", _config(tmp_path, "boussinesq"))

        assert declared["release_flux"].state != "unavailable"


class TestEveryAnswerCarriesASentence:
    @pytest.mark.parametrize("backend", ["modflow6", "modflow_nwt", "boussinesq"])
    def test_a_refusal_says_what_to_do(self, tmp_path, backend: str) -> None:
        for support in _declared(backend, _config(tmp_path, backend)).values():
            assert support.reason.strip(), f"{backend}/{support.name}"


class TestPreflightActsOnIt:
    """The payoff: the refusal arrives before the search, not at the first trial."""

    @staticmethod
    def _check(tmp_path, backend: str, support: str) -> list[str]:
        from hydromodpy.calibration.preflight import preflight_calibration

        (tmp_path / "net.gpkg").write_bytes(b"")
        outputs: dict[str, object] = {
            "target": (
                {"support": "network", "stream_geometry_path": str(tmp_path / "net.gpkg")}
                if support == "network"
                else {"support": "lake", "lake_id": "cheze", "variable": "stage"}
            )
        }
        metric = "distance_gap" if support == "network" else "rmse"
        cfg = _config(
            tmp_path,
            backend,
            param_list=["K"],
            param={
                "K": {"field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-5}}
            },
        )
        from hydromodpy.calibration.config import CalibrationConfig

        cfg.calibration = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": outputs,
                "objective_blocks": [{"name": "b", "metric": metric, "uses_outputs": ["target"]}],
            }
        )
        findings = preflight_calibration(cfg, source=tmp_path / "calib.toml")
        return [f"{item.where}: {item.detail}" for item in findings]

    def test_a_lake_output_on_nwt_is_refused_before_the_search(self, tmp_path) -> None:
        messages = " | ".join(self._check(tmp_path, "modflow_nwt", "lake"))

        assert "stage" in messages
        assert "LAK" in messages

    def test_a_lake_output_on_modflow6_without_the_lake_names_the_declaration(
        self, tmp_path
    ) -> None:
        messages = " | ".join(self._check(tmp_path, "modflow6", "lake"))

        assert "active_bc" in messages

    def test_a_network_output_passes_on_every_backend_that_serves_it(self, tmp_path) -> None:
        for backend in ("modflow6", "modflow_nwt", "boussinesq"):
            messages = " | ".join(self._check(tmp_path, backend, "network"))
            assert "release_flux" not in messages, backend
