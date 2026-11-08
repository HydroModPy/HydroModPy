"""IMS reordering method exposed in [solver.modflow6.runtime]."""

from __future__ import annotations

import pytest

from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.builders.solver_options import optional_ims_kwargs
from hydromodpy.solver.modflow6.modflow6_config import Modflow6RuntimeConfig


def test_the_reordering_method_defaults_to_none_and_writes_nothing() -> None:
    runtime = Modflow6RuntimeConfig()
    assert runtime.mf6_reordering_method == "none"
    assert "reordering_method" not in optional_ims_kwargs(runtime)


@pytest.mark.parametrize("method", ["rcm", "md"])
def test_a_reordering_method_reaches_the_ims_arguments(method: str) -> None:
    runtime = Modflow6RuntimeConfig(mf6_reordering_method=method)
    assert optional_ims_kwargs(runtime)["reordering_method"] == method


def test_the_reordering_method_is_read_from_the_runtime_table() -> None:
    config = SolverConfig.model_validate(
        {"modflow6": {"runtime": {"mf6_reordering_method": "rcm"}}}
    )
    assert config.options_of("modflow6").runtime.mf6_reordering_method == "rcm"


@pytest.mark.parametrize("method", ["rcm", "md"])
def test_the_reordering_method_reaches_the_ims_file(tmp_path, method: str) -> None:
    import flopy

    runtime = Modflow6RuntimeConfig(mf6_reordering_method=method)
    sim = flopy.mf6.MFSimulation(sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim)
    flopy.mf6.ModflowIms(
        sim, complexity="COMPLEX", filename="t.ims", **optional_ims_kwargs(runtime)
    )
    sim.write_simulation(silent=True)
    text = " ".join((tmp_path / "t.ims").read_text().upper().split())
    assert f"REORDERING_METHOD {method.upper()}" in text
