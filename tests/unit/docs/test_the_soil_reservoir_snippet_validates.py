"""The soil reservoir page's TOML has to be what a project actually loads.

The page tells a hydrogeologist to copy its ``[flow.sinks_sources.recharge.soil]``
block into a project file. A snippet that has drifted from ``SoilReservoirConfig``
would send them straight into a refusal the page does not mention.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "user_guide"
    / "soil-reservoir-recharge.rst"
)


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _dedent(block: str, indent: int) -> str:
    """Strip a fixed rst indent from every non-blank line of a code block."""
    prefix = " " * indent
    return "\n".join(
        line[indent:] if line.startswith(prefix) else line for line in block.splitlines()
    )


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _declaring_it_block() -> str:
    """The full ``Declaring it`` project block, dedented TOML text."""
    block = _between(
        _page(),
        "Declaring it\n------------\n\n.. code-block:: toml\n\n",
        "\n\nThe dates of the rain and of the ETP are those of",
    )
    return _dedent(block, 3)


def _declaring_it_snippet() -> dict:
    return tomllib.loads(_declaring_it_block())


def test_the_page_still_ships_the_declaring_it_snippet() -> None:
    assert "[flow.sinks_sources.recharge.soil]" in _page()


def test_the_soil_section_of_the_page_reads_as_a_request() -> None:
    from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig

    raw = _declaring_it_snippet()["flow"]["sinks_sources"]["recharge"]["soil"]
    config = SoilReservoirConfig(**raw)

    assert config.ru == pytest.approx(150.0)


def test_the_declaring_it_block_loads_as_a_project_file(tmp_path: Path) -> None:
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
"""
    config_path = tmp_path / "project.toml"
    config_path.write_text(boilerplate + "\n" + _declaring_it_block(), encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.recharge.soil.ru == pytest.approx(150.0)
