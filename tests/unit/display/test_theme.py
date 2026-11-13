"""Tests of the publication theme."""

from __future__ import annotations

import pytest
from matplotlib import font_manager

from hydromodpy.core.units.kinds import QUANTITY_KINDS
from hydromodpy.display import theme as th
from hydromodpy.display.request import WIDTHS_MM


def test_every_theme_holds_the_same_roles_and_ramps() -> None:
    assert set(th.THEMES) == {"default", "print", "dark"}
    base = th.THEMES["default"]
    for theme in th.THEMES.values():
        assert set(theme.roles) == set(base.roles)
        assert set(theme.ramps) == {"sequential", "diverging", "cyclic"}
        assert set(theme.quantity_ramps) == set(base.quantity_ramps)
        assert len(theme.categorical) == len(th.CATEGORICAL_ROLES)


@pytest.mark.parametrize("count", [12, 30])
def test_n_classes_get_n_colours_and_a_legend_says_when_they_run_out(count) -> None:
    theme = th.get_theme("default")
    assert len(set(theme.class_colors(count))) == count and not theme.sharing_note(count)
    assert "5 classes share" in theme.sharing_note(35)


def test_quantity_ramps_name_only_known_quantities() -> None:
    for theme in th.THEMES.values():
        assert set(theme.quantity_ramps) <= set(QUANTITY_KINDS)


def test_get_theme_refuses_an_unknown_name_and_lists_the_known_ones() -> None:
    assert th.get_theme("dark").name == "dark"
    with pytest.raises(ValueError, match=r"Known themes: dark, default, print"):
        th.get_theme("neon")


@pytest.mark.parametrize(
    ("unit", "text"),
    [
        ("m3 s-1", r"$\mathregular{m^{3}\,s^{-1}}$"),
        ("mm/day", r"$\mathregular{mm\,day^{-1}}$"),
        ("m3/s/km2", r"$\mathregular{m^{3}\,s^{-1}\,km^{-2}}$"),
        ("kg m-3", r"$\mathregular{kg\,m^{-3}}$"),
        ("m-1", r"$\mathregular{m^{-1}}$"),
        ("1", ""),
    ],
)
def test_unit_text(unit: str, text: str) -> None:
    assert th.unit_text(unit) == text


def test_widths_in_millimetres() -> None:
    assert WIDTHS_MM == {"single": 85, "medium": 120, "double": 180}


def test_the_fallback_font_is_used_when_the_font_folder_is_empty(tmp_path) -> None:
    assert th.register_fonts(tmp_path) == "DejaVu Sans"


def test_registering_the_fonts_twice_adds_them_once() -> None:
    before = len(font_manager.fontManager.ttflist)
    assert th.register_fonts(th.FONTS_DIR) == "TeX Gyre Heros"
    assert len(font_manager.fontManager.ttflist) == before
