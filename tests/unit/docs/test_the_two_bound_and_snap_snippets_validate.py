"""The two-bound network and snap-streams snippets have to load.

Three snippets on the same page: a minimal-map declaration, the extent table
of the transient two-bound mode, and ``[geographic.snap_streams]``. They are
extracted here and validated against the real Pydantic models, so a rename in
``config.py`` or ``stream_snap.py`` breaks this test rather than a reader's
terminal.
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
    / "workflows"
    / "stream-network-calibration.rst"
)


def _dedent(block: str, indent: int) -> str:
    """Strip a fixed rst indent from every non-blank line of a code block."""
    prefix = " " * indent
    return "\n".join(
        line[indent:] if line.startswith(prefix) else line for line in block.splitlines()
    )


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _minimal_map_output() -> dict:
    """The ``[calibration.outputs.seepage_network]`` snippet with a minimal map."""
    block = _between(
        _page(),
        "reaches, may be declared beside it:\n\n.. code-block:: toml\n\n",
        "\n\n``minimal_observed_network",
    )
    return tomllib.loads(_dedent(block, 3))


def _extent_table() -> dict:
    """The ``[calibration.outputs.seepage_network.extent]`` snippet."""
    block = _between(
        _page(),
        "complete calendar year of a transient run:\n\n   .. code-block:: toml\n\n",
        "\n\n   For every complete calendar year",
    )
    return tomllib.loads(_dedent(block, 6))


def _snap_streams() -> dict:
    """The ``[geographic.snap_streams]`` snippet."""
    block = _between(
        _page(),
        "Off by default, three modes:\n\n.. code-block:: toml\n\n",
        "\n\n``off``",
    )
    return tomllib.loads(_dedent(block, 3))


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


def test_the_snap_streams_snippet_validates() -> None:
    from hydromodpy.core.stream_snap import SnapStreamsConfig

    raw = _snap_streams()["geographic"]["snap_streams"]
    snap = SnapStreamsConfig.model_validate(raw)

    assert snap.mode == "diagnose"
    assert snap.radius == "2 cells"
    assert snap.max_displacement_p90 == "1 cell"
    assert snap.max_rejected_share == pytest.approx(0.10)
    assert snap.enabled
