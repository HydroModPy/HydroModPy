"""The two-bound network snippets have to load.

Two snippets on the same page: a minimal-map declaration and the extent table
of the transient two-bound mode. They are extracted here and validated
against the real Pydantic models, so a rename in ``config.py`` breaks this
test rather than a reader's terminal.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "guides"
    / "score-two-maps.md"
)


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _first_toml_block_after(heading: str) -> dict:
    """The first fenced TOML block of the section that starts at ``heading``."""
    text = _page()
    assert heading in text, f"{PAGE.name} no longer has the heading {heading!r}"
    section = text.split(heading, 1)[1]
    block = section.split("```toml\n", 1)[1].split("```", 1)[0]
    return tomllib.loads(block)


def _minimal_map_output() -> dict:
    """The ``[calibration.outputs.seepage_network]`` snippet with a minimal map."""
    return _first_toml_block_after("## 1. Declare the two maps")


def _extent_table() -> dict:
    """The ``[calibration.outputs.seepage_network.extent]`` snippet."""
    return _first_toml_block_after("## 2. Declare the extent table")


def test_the_minimal_map_snippet_names_the_two_files() -> None:
    doc = _minimal_map_output()

    output = doc["calibration"]["outputs"]["seepage_network"]
    assert output["stream_geometry_path"] == "complete_network.gpkg"
    assert output["minimal_stream_geometry_path"] == "permanent_network.gpkg"


def test_the_minimal_map_snippet_validates_as_a_network_output() -> None:
    from hydromodpy.calibration.config import CalibOutputNetwork, validate_calib_output

    output = validate_calib_output(
        _minimal_map_output()["calibration"]["outputs"]["seepage_network"]
    )

    assert isinstance(output, CalibOutputNetwork)
    assert output.has_minimal_map


def test_the_extent_table_snippet_validates_with_its_default_weights() -> None:
    from hydromodpy.calibration.config import CalibNetworkExtent

    raw = _extent_table()["calibration"]["outputs"]["seepage_network"]["extent"]
    extent = CalibNetworkExtent.model_validate(raw)

    assert extent.maximal_flowing_steps == 1
    assert extent.minimal_dry_steps == 1
    assert extent.year_quorum == pytest.approx(0.5)
    assert extent.visible_flow == "1 L/s"
    assert extent.weights.minimal == pytest.approx(0.5)
    assert extent.weights.maximal == pytest.approx(0.5)


def test_the_two_snippets_together_validate_as_one_two_bound_output() -> None:
    """The minimal map and the extent table, combined, are what a real project writes."""
    from hydromodpy.calibration.config import CalibOutputNetwork, validate_calib_output

    output_doc = _minimal_map_output()["calibration"]["outputs"]["seepage_network"]
    output_doc["extent"] = _extent_table()["calibration"]["outputs"]["seepage_network"]["extent"]

    output = validate_calib_output(output_doc)

    assert isinstance(output, CalibOutputNetwork)
    assert output.extent is not None
    assert output.time == "last"
