"""The CLI banner: every letter is drawn whole in its group's color."""

from __future__ import annotations

from hydromodpy.cli import banner


def test_the_color_changes_only_on_a_blank_column() -> None:
    """A split inside a stroke draws one letter in two colors."""
    for line, (hydro_end, mod_end) in zip(banner._LETTER_LINES, banner._SPLITS, strict=True):
        assert line[hydro_end - 1] == " ", line
        assert line[mod_end - 1] == " ", line


def test_the_footer_colors_the_strokes_and_dims_the_words() -> None:
    descender, tagline, swash = banner._FOOTER_SPLITS
    assert set(banner._FOOTER[descender:tagline]) == {"/", "_"}
    assert set(banner._FOOTER[swash:]) == {"/", "_"}
    assert banner._FOOTER[tagline:swash].strip() == "Hydrological Modelling in Python"


def test_the_banner_prints_the_whole_art() -> None:
    assert banner._banner().plain.splitlines() == [*banner._LETTER_LINES, banner._FOOTER]
