"""The soil reservoir section the theory page prints has to load.

The page lists every key of ``[flow.sinks_sources.recharge.soil]`` in one
block. A block that drifted from ``SoilReservoirConfig`` would show a reader
a section the code refuses.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[3] / "docs" / "source" / "theory" / "soil-reservoir.md"
_BLOCK = re.compile(r"```\{hmp-toml\}\n(\[flow\.sinks_sources\.recharge\.soil\]\n.*?)```", re.S)


def _block() -> str:
    match = _BLOCK.search(PAGE.read_text(encoding="utf-8"))
    assert match, "theory/soil-reservoir.md no longer prints its soil section"
    return match.group(1)


def test_the_soil_section_of_the_page_reads_as_a_request() -> None:
    from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig

    raw = tomllib.loads(_block())["flow"]["sinks_sources"]["recharge"]["soil"]
    config = SoilReservoirConfig(**raw)

    assert config.ru == pytest.approx(150.0)


def test_the_soil_section_loads_as_a_project_file(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig

    boilerplate = f"""
[workflow]
mode = "simulation"

[workspace]
project_root = "{tmp_path.as_posix()}"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "soil_page_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

# What a project needs around the soil section: daily rain and ETP to read,
# the recharge and the residual ETP sent to MODFLOW, a first period that is
# not a one-day steady state.
[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"

[flow]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"
"""
    config_path = tmp_path / "project.toml"
    config_path.write_text(boilerplate + "\n" + _block(), encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == pytest.approx(150.0)
