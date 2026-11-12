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

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.base.observables import ObservableSupport

LAKES = {"lakes": {"cheze": {"bedleak": 1e-6, "initial_stage": "10 m"}}}


def _config(tmp_path, backend: str, **flow: object):
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.mesh.mesh_config import MeshConfig
    from hydromodpy.solver.base.solver_config import SolverConfig

    # Boussinesq reads triangles only: the validator refuses the default grid.
    mesh = MeshConfig(engine="triangle") if backend == "boussinesq" else None
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        solver=SolverConfig(backend=backend),
        flow=FlowConfig(**flow),
        mesh=mesh,
    )


def _declared(backend: str, cfg) -> dict[str, ObservableSupport]:
    import importlib

    module, cls = {
        "modflow6": ("hydromodpy.solver.modflow6.adapter", "Modflow6FlowAdapter"),
        "modflow_nwt": ("hydromodpy.solver.modflow_nwt.adapter", "ModflowNwtFlowAdapter"),
        "boussinesq": ("hydromodpy.solver.boussinesq.adapter", "BoussinesqFlowAdapter"),
    }[backend]
    adapter = getattr(importlib.import_module(module), cls)()
    active = frozenset(cfg.flow.active_bc or ())
    return {item.name: item for item in adapter.declared_observables(active)}


class TestTheThirdState:
    def test_declaring_the_lake_makes_it_servable(self, tmp_path) -> None:
        declared = _declared("modflow6", _config(tmp_path, "modflow6", sinks_sources=LAKES))

        assert declared["stage"].is_servable_now

    def test_a_lake_stage_is_never_servable_under_nwt(self, tmp_path) -> None:
        declared = _declared("modflow_nwt", _config(tmp_path, "modflow_nwt"))

        assert declared["stage"].can_never_be_served
        assert "LAK" in declared["stage"].reason


class TestPreflightActsOnIt:
    """The payoff: the refusal arrives before the search, not at the first trial."""

    @staticmethod
    def _check(tmp_path, backend: str, support: str) -> list[str]:
        from hydromodpy.calibration.preflight import preflight_calibration

        (tmp_path / "net.gpkg").write_bytes(b"")
        outputs: dict[str, object] = {
            "target": (
                {"support": "network", "map": {"complete": str(tmp_path / "net.gpkg")}}
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
        return [f"{item.path}: {item.detail}" for item in findings]

    def test_a_network_output_on_boussinesq_says_what_to_use(self, tmp_path) -> None:
        messages = " | ".join(self._check(tmp_path, "boussinesq", "network"))

        assert "release_flux" in messages
        assert "MODFLOW" in messages
