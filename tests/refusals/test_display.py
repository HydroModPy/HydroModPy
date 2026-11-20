"""A figure name of a pre-release is refused with the form that replaces it."""

from __future__ import annotations

import pytest

from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import (
    FigureRequest,
    expand,
    request_of,
    retired,
    retired_forms,
    retired_table,
)

ROWS = retired_table()
WITH_FIGURE = {name: row for name, row in ROWS.items() if "figure" in row}
WITH_NONE = {name: row for name, row in ROWS.items() if "none" in row}


def forms_of(name: str) -> list[dict]:
    form = ROWS[name]["figure"]
    return [form] if isinstance(form, dict) else form


def test_the_table_holds_73_names_and_each_gives_one_answer() -> None:
    assert len(ROWS) == 73
    assert not WITH_FIGURE.keys() & WITH_NONE.keys()
    assert WITH_FIGURE.keys() | WITH_NONE.keys() == ROWS.keys()


@pytest.mark.parametrize("name", WITH_FIGURE)
def test_each_replacing_form_is_a_valid_request(name: str) -> None:
    for form in forms_of(name):
        expand(FigureRequest.model_validate(form), PRESETS)


@pytest.mark.parametrize("name", WITH_FIGURE)
def test_the_sentence_gives_the_forms_in_toml_and_in_python(name: str) -> None:
    text = retired(name)
    assert text.startswith(f"{name!r} was a figure of a pre-release. Write [[display.figure]] ")
    for toml, call in retired_forms(name):
        assert toml in text
        assert call in text
    assert text.endswith(f" Lost: {ROWS[name]['lost']}" if "lost" in ROWS[name] else call + ".")


@pytest.mark.parametrize("name", WITH_NONE)
def test_a_name_with_no_replacement_says_why(name: str) -> None:
    assert retired(name) == f"{name!r} was a figure of a pre-release. {ROWS[name]['none']}"


def test_a_name_the_table_lacks_is_not_retired() -> None:
    assert retired("never_a_figure") is None


def test_a_former_name_is_refused_with_its_variable() -> None:
    with pytest.raises(ValueError, match="watertable_elevation"):
        expand(request_of("piezometric_map", PRESETS), PRESETS)


def test_a_former_name_that_is_a_preset_still_draws() -> None:
    assert "hydrograph" in ROWS
    assert expand(request_of("hydrograph", PRESETS), PRESETS).panels
