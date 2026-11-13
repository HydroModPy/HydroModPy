"""The presets: their table, and the figures they name exist."""

from __future__ import annotations

import pytest

from hydromodpy.display.presets import PRESETS as FIGURE_PRESETS
from hydromodpy.display.report.engine import LEVELS
from hydromodpy.display.report.presets import PRESETS, REPORT_FIGURES, SHEET_FIGURES, preset_figures
from hydromodpy.display.request import expand, file_stem


@pytest.mark.parametrize(
    ("name", "levels", "counts"),
    [("research", True, (3, 6, 6)), ("management", False, (3, 0, 0))],
)
def test_preset_shape(name, levels, counts):
    preset = PRESETS[name]
    assert preset.name == name
    assert preset.levels is levels
    assert tuple(len(preset.figures[level]) for level in LEVELS) == counts


def test_a_figure_is_named_once_per_preset():
    names = [n for level in LEVELS for n in PRESETS["research"].figures[level]]
    assert len(names) == len(set(names)) == 15


def test_every_stem_names_a_request_that_expands():
    stems = [*preset_figures(PRESETS["research"]), *SHEET_FIGURES]
    assert [s for s in stems if s not in REPORT_FIGURES] == []
    for stem, request in REPORT_FIGURES.items():
        assert file_stem(request) == stem
        assert expand(request, FIGURE_PRESETS).stem == stem


def test_sheet_is_the_compact_level_of_management():
    assert PRESETS["management"].figures["compact"] == SHEET_FIGURES


def test_research_names_eight_panels():
    assert len(PRESETS["research"].panels) == 8


def test_cli_choices_are_the_preset_keys():
    from hydromodpy.cli.commands.show import REPORT_PRESETS

    assert tuple(REPORT_PRESETS) == tuple(PRESETS)
