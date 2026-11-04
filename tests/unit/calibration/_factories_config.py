"""Factories of the config, preflight, targets and parameter-resolution tests.

A calibration document is written in a test as a few lines. A line ``@NAME``
stands for one of the shared tables of ``MACROS`` and ``toml_doc`` expands it.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from hydromodpy.calibration.preflight import PreflightFinding, preflight_calibration
from hydromodpy.config import HydroModPyConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from tests.unit.calibration._factories import _Project

MACROS = {
    "GRID": '[calibration]\nmethod = "grid"',
    "GRID4": (
        '[calibration]\nmethod = "grid"\nmax_trials = 4\nmethod_options = { points_per_dim = 2 }'
    ),
    "K": '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\npath = "flow.param.K.field.value"',
    "KLOG": (
        '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\nsearch_space = "log"\n'
        'path = "flow.param.K.field.value"\nunits = "m/s"'
    ),
    "KB": "[calibration.parameters.K]\nbounds = [1e-7, 1e-3]",
    "SY": (
        "[calibration.parameters.Sy]\nbounds = [1e-3, 0.35]\n"
        'path = "flow.param.Sy.field.value"\nunits = "-"'
    ),
    "NET": (
        '[calibration.outputs.net]\nsupport = "network"\nstream_geometry_path = "streams.gpkg"'
    ),
    "NETROOT": (
        '[calibration.outputs.net]\nsupport = "network"\n'
        'stream_geometry_path = "PROJECT_ROOT/net.gpkg"'
    ),
    "GAP": (
        '[[calibration.objective_blocks]]\nname = "gap"\nmetric = "distance_gap"\n'
        'uses_outputs = ["net"]'
    ),
    "GHOST": (
        '[[calibration.objective_blocks]]\nname = "gap"\nmetric = "rmse"\nuses_outputs = ["ghost"]'
    ),
    "UNC": '[calibration.uncertainty]\nmethod = "linearized"\nperturbation = 0.01',
    "GAUGE": (
        '[calibration.outputs.gauge]\nvariable = "discharge"\nsupport = "boundary"\n'
        'boundary_id = "outlet"\nobserves = "NANCON"'
    ),
}

PROJECT_BASE = """
[workspace]
[workflow]
mode = "calibration"
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"
[geographic]
source_mode = "synthetic"
[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5
[flow.param.Sy.field]
id = "Sy"
kind = "homogeneous"
unit = "-"
value = 0.05
"""

PROCESS = """
[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]
"""


def toml_doc(text: str) -> str:
    """Expand the ``@NAME`` lines of a test document."""
    return re.sub(
        r"^[ \t]*@(\w+)[ \t]*$", lambda match: MACROS[match[1]], textwrap.dedent(text), flags=re.M
    )


def write_calibration(
    tmp_path: Path, *sections: str, base: str = PROJECT_BASE, name: str = "calib.toml"
) -> Path:
    """Write the project base plus the sections, `PROJECT_ROOT` standing for `tmp_path`."""
    path = tmp_path / name
    (tmp_path / "net.gpkg").write_bytes(b"")
    text = base + "".join(toml_doc(section) for section in sections)
    path.write_text(text.replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")
    return path


def messages(findings) -> str:
    return " | ".join(f"{item.where}: {item.detail}" for item in findings)


def run_preflight(path: Path) -> list[PreflightFinding]:
    """Load the way the CLI does, then check; loading lives a layer above."""
    try:
        cfg = HydroModPyConfig.from_toml(path)
    except Exception as exc:
        return [PreflightFinding("error", path.name, f"the file does not load: {exc}")]
    return preflight_calibration(cfg, source=path)


def preflight_of(tmp_path: Path, *sections: str, **options) -> list[PreflightFinding]:
    return run_preflight(write_calibration(tmp_path, *sections, **options))


def sinks_project(**sinks_sources: object) -> _Project:
    """A homogeneous flow carrying the given sinks and sources."""
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(
        update={"sinks_sources": FlowSinksSourcesConfig(**sinks_sources)}
    )
    return _Project(flow)


def soil_project(**soil: object) -> _Project:
    return sinks_project(recharge=FlowRechargeConfig(soil=SoilReservoirConfig(ru=150.0, **soil)))
