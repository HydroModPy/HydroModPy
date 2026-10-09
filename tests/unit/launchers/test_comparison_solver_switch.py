"""A comparison child that changes the flow solver keeps a coherent file."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.comparison.runtime.config import (
    _build_solver_process_overlay,
    _let_solver_backend_follow_the_process,
    write_toml_payload,
)
from hydromodpy.config import HydroModPyConfig

_BASE = """
[workflow]
mode = "simulation"

[workspace]
project_root = "."

[geographic.catchment]
catch_def = "dem"
dem_init_path = "dem.tif"

[solver]
backend = { backend = "modflow6" }

[[simulation.process]]
id = "mesh_main"
type = "mesh"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]
"""


def test_child_keeps_every_process_and_follows_the_new_solver(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text(_BASE, encoding="utf-8")

    processes = _build_solver_process_overlay(base_config_path=base, solver="modflow_nwt")
    overlay = {"simulation": {"process": processes}}
    _let_solver_backend_follow_the_process(overlay)
    child = tmp_path / "child.toml"
    write_toml_payload(child, {"base_config": base.as_posix(), **overlay})

    cfg = HydroModPyConfig.from_toml(child)

    assert [process.id for process in cfg.simulation.process] == ["mesh_main", "flow_main"]
    assert cfg.simulation.process[1].solvers == ["modflow_nwt"]
    assert cfg.solver.backend_name == "modflow_nwt"
