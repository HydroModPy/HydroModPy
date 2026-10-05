"""``rectify_on_mesh`` no longer needs ``condition_top``: the TOML loads without it.

The channel is traced on the descent D, a filled copy of the solver top, so the
solver top is never raised for the routing.
"""

from __future__ import annotations

from hydromodpy.config import HydroModPyConfig


def _toml(project_root) -> str:
    return f"""
[workflow]
mode = "simulation"

[workspace]
project_root = "{project_root.as_posix()}"

[geographic]
source_mode = "synthetic"

[modflow6.sgrid]
condition_top = false

[flow]
active_bc = ["sfr"]

[flow.sinks_sources.sfr.nancon]
stream_threshold_km2 = 1.5
rectify_on_mesh = true
route_drainage = true

[flow.sinks_sources.sfr.nancon.width]
kind = "constant"
value = "2 m"
"""


def test_rectify_on_mesh_loads_with_condition_top_false(tmp_path):
    path = tmp_path / "project.toml"
    path.write_text(_toml(tmp_path), encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(path)

    sfr = cfg.flow.sinks_sources.sfr["nancon"]
    assert sfr.rectify_on_mesh is True
    assert cfg.modflow6.sgrid.condition_top is False
