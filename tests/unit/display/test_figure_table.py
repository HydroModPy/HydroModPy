"""Unit tests for the generated figure_table.py and lightweight display validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.figure_table import (
    FIGURES,
    FORMER_NAMES,
    OPTIONS,
    PYTHON_ONLY_OPTIONS,
)
from tools.figure_table import generate_figure_table_source

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.allow_subprocess
def test_figure_table_file_matches_generator() -> None:
    """The on-disk figure_table.py must match the generator in tools.figure_table."""
    target_path = REPO_ROOT / "hydromodpy" / "display" / "figure_table.py"
    expected = generate_figure_table_source()
    actual = target_path.read_text(encoding="utf-8")
    assert actual == expected, "figure_table.py is out of date. Run: python -m tools.figure_table"


# The fresh-interpreter check that [display] imports no figure module lives at
# tests/integration/display/test_display_config_validation.py: a subprocess
# cannot run in this tier, and only a fresh interpreter sees the first import.


def test_figure_table_contents() -> None:
    """The generated table holds 70 figures and valid mappings."""
    assert len(FIGURES) == 70
    assert "hydrograph" in FIGURES
    assert "abherve_two_stage_card" in FORMER_NAMES
    assert FORMER_NAMES["abherve_two_stage_card"] == "matching_hydrographic_network_card"

    for name, path in FIGURES.items():
        assert path.startswith("hydromodpy.display.figures.")
        assert ":" in path
        assert name in OPTIONS

    for name, py_opts in PYTHON_ONLY_OPTIONS.items():
        assert name in FIGURES
        assert isinstance(py_opts, tuple)
