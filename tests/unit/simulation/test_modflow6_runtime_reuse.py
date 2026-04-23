from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.options import ModflowRunOptions


def _build_flow_run_context(*, flow_runtime_overrides: dict[str, object] | None):
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow6",
                process_id="flow_main",
                process_type="flow",
                solver="modflow6",
            ),
        ),
    )
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            modflow6=SimpleNamespace(),
            postprocess=SimpleNamespace(
                flow=SimpleNamespace(
                    intermittency=SimpleNamespace(
                        yearly=False,
                        monthly=False,
                        weekly=False,
                        daily=False,
                    ),
                    native_mesh_npz=False,
                    native_mesh_csv=False,
                    native_mesh_vtu=False,
                    native_mesh_png=False,
                )
            ),
        ),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(dem_res=1.0, xmin=0.0, ymax=1.0),
            workspace=SimpleNamespace(simulations_folder="unused", bin_path="bin"),
            flow=SimpleNamespace(active_bc=[]),
            domain=SimpleNamespace(),
            flow_runtime_overrides=flow_runtime_overrides,
        ),
        execution=SimpleNamespace(models_by_run_id={}),
    )
    return RunContext(plan=plan, run=plan.runs[0], state=state)


def test_modflow6_flow_adapter_reuses_solver_instance(monkeypatch) -> None:
    build_calls: list[str] = []

    class _FakeModel:
        def __init__(
            self,
            geographic,
            *,
            model_folder,
            model_name,
            bin_path,
            modflow_config,
            preprocess_options,
        ) -> None:
            del geographic, bin_path, modflow_config, preprocess_options
            self.model_name = model_name
            self.full_path = str(Path(model_folder) / model_name)
            build_calls.append(str(model_name))

        def pre_processing(self, **kwargs) -> None:
            self.pre_kwargs = dict(kwargs)

        def processing(self, options) -> bool:
            del options
            return True

        def post_processing(self, options) -> None:
            del options

    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.adapters.flow.Modflow6",
        _FakeModel,
    )

    adapter = Modflow6FlowAdapter()
    ctx = _build_flow_run_context(
        flow_runtime_overrides={
            "source": "model_calibration",
            "reuse_solver_model": True,
            "model_name_override": "stable_runtime_model",
        }
    )

    adapter.execute(ctx)
    adapter.execute(ctx)

    assert build_calls == ["stable_runtime_model"]


def test_modflow6_processing_writes_only_dirty_packages() -> None:
    class _FakePackage:
        def __init__(self) -> None:
            self.write_calls = 0

        def write(self, *args, **kwargs) -> None:
            del args, kwargs
            self.write_calls += 1

    class _FakeSimulation:
        def __init__(self) -> None:
            self.write_calls = 0
            self.run_calls = 0

        def write_simulation(self, *args, **kwargs) -> None:
            del args, kwargs
            self.write_calls += 1

        def run_simulation(self, *args, **kwargs):
            del args, kwargs
            self.run_calls += 1
            return True, None

    model = object.__new__(Modflow6)
    model.sim = _FakeSimulation()
    model.npf = _FakePackage()
    model.sto = _FakePackage()
    model.drn = _FakePackage()
    model._runtime_dirty_packages = ("npf", "sto")

    success = Modflow6.processing(
        model,
        ModflowRunOptions(write_model=True, run_model=True),
    )

    assert success is True
    assert model.sim.write_calls == 0
    assert model.sim.run_calls == 1
    assert model.npf.write_calls == 1
    assert model.sto.write_calls == 1
    assert model.drn.write_calls == 0
    assert model._runtime_dirty_packages == ()
