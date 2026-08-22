"""The TOML printed in the how-to page has to validate through the real schema.

A configuration example nobody parses drifts from the code within one release,
and the reader has no way of telling. This parses the block out of the page and
runs it through the loader the CLI uses.
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
    / "user_guide"
    / "workflows"
    / "stream-network-calibration.rst"
)

BLOCK = re.compile(r"\.\. code-block:: toml\n\n((?:(?:   .*)?\n)+)")


def _documented_configuration() -> str:
    blocks = BLOCK.findall(PAGE.read_text(encoding="utf-8"))
    assert blocks, f"no TOML block in {PAGE.name}"
    longest = max(blocks, key=len)
    return "\n".join(line[3:] for line in longest.splitlines())


@pytest.fixture
def loaded(tmp_path: Path):
    # The page starts the block with base_config, which is the point: the
    # loader has to resolve it the way the pipeline does.
    (tmp_path / "project.toml").write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    path = tmp_path / "calibration.toml"
    path.write_text(_documented_configuration(), encoding="utf-8")
    return load_toml_calibration(path)


def test_the_documented_configuration_validates(loaded) -> None:
    cfg, raw = loaded
    assert [phase.name for phase in cfg.phases] == ["steady_k_over_r", "transient_sy"]
    assert [phase.method for phase in cfg.phases] == ["bisection", "grid"]
    assert cfg.phases[1].depends_on == "steady_k_over_r"


def test_the_base_configuration_is_resolved(loaded) -> None:
    _cfg, raw = loaded
    assert "workflow" in raw


def test_the_network_output_and_its_block_are_paired(loaded) -> None:
    cfg, _raw = loaded
    assert cfg.outputs["seepage_network"].support == "network"
    assert cfg.objective_blocks[0].metric == "distance_gap"
    assert cfg.objective_blocks[0].uses_outputs == ["seepage_network"]


def test_the_two_stages_carry_what_the_page_claims(loaded) -> None:
    cfg, _raw = loaded
    steady, transient = cfg.phases
    assert steady.optimizer_kwargs == {"rel_tol": 0.01, "sweep_points": 7}
    assert steady.freeze_on_success is True
    assert transient.objective == "nse_log"
    assert transient.scoring_window.start == "2012-01-01"
    assert transient.scoring_window.end == "2015-12-31"
