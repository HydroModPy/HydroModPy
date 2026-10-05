"""``rectify_on_mesh`` needs nothing from the solver top, and the keys that went are refused.

The channel is traced on the descent D, a filled copy of the solver top, so the
solver top is never raised for the routing. The solver top conditioning keys and
the SFR threshold no longer exist: a TOML that still declares one fails to load.
"""

from __future__ import annotations

import re

import pytest

from hydromodpy.config import HydroModPyConfig


def _toml(
    project_root, *, sgrid: str = "", top_sampling: str = "", nwt: str = "", sfr: str = ""
) -> str:
    return f"""
[workflow]
mode = "simulation"

[workspace]
project_root = "{project_root.as_posix()}"

[geographic]
source_mode = "synthetic"

[modflow6.sgrid]
{sgrid}

[modflow6.sgrid.top_sampling]
{top_sampling}

[modflownwt.sgrid]
{nwt}

[flow]
active_bc = ["sfr"]

[flow.sinks_sources.sfr.nancon]
rectify_on_mesh = true
route_drainage = true
{sfr}

[flow.sinks_sources.sfr.nancon.width]
kind = "constant"
value = "2 m"
"""


def _load(tmp_path, **kwargs) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(_toml(tmp_path, **kwargs), encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


def test_rectify_on_mesh_loads_without_any_solver_top_key(tmp_path):
    cfg = _load(tmp_path)

    sfr = cfg.flow.sinks_sources.sfr["nancon"]
    assert sfr.rectify_on_mesh is True
    assert sfr.route_drainage is True


@pytest.mark.parametrize(
    ("where", "line", "dotted"),
    [
        ("sgrid", "condition_top = true", "modflow6.sgrid.condition_top"),
        ("sgrid", "condition_top_epsilon = 0.01", "modflow6.sgrid.condition_top_epsilon"),
        (
            "top_sampling",
            "network_safety_net = true",
            "modflow6.sgrid.top_sampling.network_safety_net",
        ),
        (
            "top_sampling",
            "max_channel_lowering_m = 2.0",
            "modflow6.sgrid.top_sampling.max_channel_lowering_m",
        ),
        ("nwt", "condition_top = true", "modflownwt.sgrid.condition_top"),
        ("sfr", "stream_threshold_km2 = 1.5", "stream_threshold_km2"),
        ("sfr", "stream_threshold_cells = 50", "stream_threshold_cells"),
    ],
)
def test_a_removed_key_is_refused_by_name(tmp_path, where, line, dotted):
    with pytest.raises(Exception, match=re.escape(dotted) + r"\b(?!_)"):
        _load(tmp_path, **{where: line})
