"""The presets: their table, and the figures they name exist."""

from __future__ import annotations

import pytest

from hydromodpy.display.figure_table import FIGURES
from hydromodpy.display.report.engine import LEVELS
from hydromodpy.display.report.presets import PRESETS, SHEET_FIGURES, preset_figures


def test_preset_names():
    assert sorted(PRESETS) == ["management", "research"]


@pytest.mark.parametrize(
    ("name", "levels", "counts"),
    [("research", True, (3, 9, 8)), ("management", False, (3, 0, 0))],
)
def test_preset_shape(name, levels, counts):
    preset = PRESETS[name]
    assert preset.name == name
    assert preset.levels is levels
    assert tuple(len(preset.figures[level]) for level in LEVELS) == counts


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_named_figures_are_registered(name):
    assert [n for n in preset_figures(PRESETS[name]) if n not in FIGURES] == []


def test_a_figure_is_named_once_per_preset():
    names = [n for level in LEVELS for n in PRESETS["research"].figures[level]]
    assert len(names) == len(set(names)) == 20


def test_sheet_names_three_figures():
    assert PRESETS["management"].figures["compact"] == SHEET_FIGURES
    assert len(SHEET_FIGURES) == 3


def test_research_names_eight_panels():
    assert len(PRESETS["research"].panels) == 8


def test_cli_choices_are_the_preset_keys():
    from hydromodpy.cli.commands.report import REPORT_PRESETS

    assert tuple(REPORT_PRESETS) == tuple(PRESETS)
