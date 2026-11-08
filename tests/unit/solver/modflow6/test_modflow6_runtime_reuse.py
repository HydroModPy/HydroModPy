from __future__ import annotations

from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from tests._helpers.model_factory import make_model


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
    model.nper = 1
    model.inputs = make_model()
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
