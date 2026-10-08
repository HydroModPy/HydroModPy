"""The TOML printed in the stream network guide has to load through the real schema.

A configuration example nobody parses drifts from the code within one release,
and the reader has no way of telling. This parses the block out of the page,
runs it through the loader the CLI uses, and checks the two stages the page
says the protocol writes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "guides"
    / "calibrate-on-the-stream-network.md"
)

BLOCK = re.compile(r"^```toml\n(.*?)^```$", re.MULTILINE | re.DOTALL)
BASE_CONFIG = re.compile(r'^base_config = "(.+)"$', re.MULTILINE)


def _documented_configuration() -> str:
    blocks = [
        block
        for block in BLOCK.findall(PAGE.read_text(encoding="utf-8"))
        if "[calibration.protocol]" in block
    ]
    assert len(blocks) == 1, f"expected one protocol configuration in {PAGE.name}"
    return blocks[0]


@pytest.fixture
def loaded(tmp_path: Path):
    # The page starts the block with base_config, which is the point: the
    # loader has to resolve it the way the pipeline does.
    text = _documented_configuration()
    base = BASE_CONFIG.search(text)
    assert base, f"the protocol block of {PAGE.name} names no base_config"
    (tmp_path / base.group(1)).write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return load_toml_calibration(path)


def test_the_documented_configuration_validates(loaded) -> None:
    cfg, raw = loaded
    assert "workflow" in raw
    assert [phase.name for phase in cfg.phases] == ["steady_conductivity", "transient_storage"]


def test_stage_one_moves_k_alone_by_bisection_on_the_network(loaded) -> None:
    cfg, _raw = loaded
    steady = cfg.phases[0]
    assert steady.parameters == ["K"]
    assert steady.method == "bisection"
    assert cfg.outputs["seepage_network"].support == "network"
    assert cfg.objective_blocks[0].metric == "distance_gap"
    assert cfg.objective_blocks[0].uses_outputs == ["seepage_network"]


def test_stage_two_moves_sy_alone_with_k_frozen(loaded) -> None:
    cfg, _raw = loaded
    steady, transient = cfg.phases
    assert transient.parameters == ["Sy"]
    assert transient.depends_on == "steady_conductivity"
    assert steady.freeze_on_success is True
