"""Renaming a figure must not break the project files that list it.

A figure name is written in ``[display].figures`` and validated against the
registry, so a rename is a hard refusal for every project that already asks for
it. Nothing said a figure used to be called something else, which is why a name
that says the wrong thing tends to keep it.

The seam is the same one configuration keys use: the figure declares what it was
called, the old name still resolves, and using it warns with both names.
"""

from __future__ import annotations

import warnings

import pytest

from hydromodpy.display import figure_registry
from hydromodpy.display.config import DisplayConfig


def test_the_current_name_resolves_without_a_word() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (
            figure_registry.resolve("matching_hydrographic_network_card")
            == "matching_hydrographic_network_card"
        )


def test_the_former_name_still_resolves() -> None:
    with pytest.warns(DeprecationWarning):
        assert (
            figure_registry.resolve("abherve_two_stage_card")
            == "matching_hydrographic_network_card"
        )


def test_the_warning_names_both() -> None:
    with pytest.warns(DeprecationWarning) as caught:
        figure_registry.resolve("abherve_two_stage_card")

    message = str(caught[0].message)
    assert "abherve_two_stage_card" in message
    assert "matching_hydrographic_network_card" in message


def test_an_unknown_name_is_still_refused() -> None:
    with pytest.raises(KeyError):
        figure_registry.resolve("no_such_figure")


def test_only_current_names_are_listed() -> None:
    listed = set(figure_registry.names())

    assert "matching_hydrographic_network_card" in listed
    assert "abherve_two_stage_card" not in listed


def test_getting_the_figure_by_its_former_name_returns_the_figure() -> None:
    with pytest.warns(DeprecationWarning):
        figure = figure_registry.get("abherve_two_stage_card")

    assert figure.spec.name == "matching_hydrographic_network_card"


def test_a_display_section_listing_the_former_name_loads_and_is_rewritten() -> None:
    """Downstream sees one name, so nothing has to know about the other."""
    with pytest.warns(DeprecationWarning):
        cfg = DisplayConfig(figures=["abherve_two_stage_card"])

    assert cfg.figures == ["matching_hydrographic_network_card"]


def test_a_display_section_still_refuses_a_typo() -> None:
    with pytest.raises(ValueError, match="unknown figure"):
        DisplayConfig(figures=["abherve_two_stage_crad"])
