"""A key a figure does not take is refused when the config loads.

Every figure ``render`` ends with a ``**`` parameter, so ``timstep = 33`` in
``[display.overrides.seepage_map]`` used to pass ``hmp config check`` and draw
the last step without a word. The accepted keys are read off the figure's own
``plot`` and ``render`` signatures, so the check needs no second declaration
that could drift from the code.
"""

from __future__ import annotations

import datetime
import warnings

import pytest
from pydantic import ValidationError

from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure_registry import figure_option_names, names
from hydromodpy.display.runs import figure_options_from_run

REGISTERED = sorted(names())


@pytest.mark.parametrize("figure", REGISTERED)
def test_every_key_a_figure_takes_loads(figure: str) -> None:
    accepted = figure_option_names(figure)
    assert "figsize" in accepted
    assert "timestep" not in accepted
    assert "dpi" not in accepted

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        config = DisplayConfig(overrides={figure: {key: None for key in accepted}})

    assert set(config.overrides[figure]) == set(accepted)


@pytest.mark.parametrize("figure", REGISTERED)
def test_a_misspelt_key_is_refused_with_the_keys_the_figure_takes(figure: str) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={figure: {"timstep": 33}})

    message = str(caught.value)
    assert f"[display.overrides.{figure}] has no option 'timstep'" in message
    assert ", ".join(sorted(figure_option_names(figure))) in message


def test_the_figures_that_draw_one_instant_take_time() -> None:
    instant = {name for name in REGISTERED if "time" in figure_option_names(name)}

    assert {"seepage_map", "cross_section", "piezometric_map"} <= instant
    assert "hydrograph" not in instant
    with pytest.raises(ValidationError, match="hydrograph takes: figsize, log_y"):
        DisplayConfig(overrides={"hydrograph": {"time": "last"}})


def test_a_key_under_a_misplaced_table_header_is_refused() -> None:
    # In TOML a table header swallows every key below it: `figures` written
    # after [display.overrides.seepage_map] lands in that table.
    with pytest.raises(ValidationError, match="has no option 'figures'"):
        DisplayConfig(overrides={"seepage_map": {"figures": ["seepage_map"]}})


def test_the_former_timestep_key_loads_as_time_and_warns() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        config = DisplayConfig(overrides={"cross_section": {"timestep": 33, "orientation": "sn"}})

    assert config.overrides["cross_section"] == {"time": 33, "orientation": "sn"}
    assert "'timestep' is now called 'time' ([display.overrides.cross_section])" in str(
        caught[0].message
    )


def test_both_spellings_in_one_table_are_refused_naming_the_line_to_delete() -> None:
    # A base that writes time and a calibration phase override that still
    # writes ".timestep" merge into one table holding both.
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={"seepage_map": {"time": "2002-10-15", "timestep": 0}})

    message = str(caught.value)
    assert "was given both 'timestep' and 'time'" in message
    assert "delete the 'timestep' line" in message
    assert '"display.overrides.seepage_map.timestep"' in message


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("2002-10-15", "2002-10-15"),
        (datetime.date(2002, 10, 15), "2002-10-15"),
        ("first", "first"),
        ("LAST", "last"),
        (33, 33),
        (-1, -1),
    ],
)
def test_a_time_takes_a_date_first_last_or_an_index(value, stored) -> None:
    gallery = DisplayConfig(time=value)
    figure = DisplayConfig(overrides={"seepage_map": {"time": value}})

    assert gallery.time == stored
    assert figure.overrides["seepage_map"]["time"] == stored


@pytest.mark.parametrize("value", ["yesterday", "October 2002", "2002-13-45", True, ["last"]])
def test_a_time_of_another_shape_is_refused(value) -> None:
    with pytest.raises(ValidationError, match="display.time"):
        DisplayConfig(time=value)
    with pytest.raises(ValidationError, match="display.overrides.seepage_map.time"):
        DisplayConfig(overrides={"seepage_map": {"time": value}})


class _SealedRun:
    """A run as ``hmp viz show`` reads it: the config snapshot it sealed."""

    def __init__(self, display: dict | None) -> None:
        full = DisplayConfig().model_dump(mode="json")
        self.config_snapshot = None if display is None else {"display": {**full, **display}}


def test_a_redraw_takes_the_options_the_run_was_drawn_with() -> None:
    run = _SealedRun({"time": "2002-10-15", "overrides": {"cross_section": {"orientation": "sn"}}})

    assert figure_options_from_run(run, "cross_section") == {
        "time": "2002-10-15",
        "orientation": "sn",
    }
    # The schema default of cmap, spelled out by every snapshot, is not a choice.
    assert figure_options_from_run(run, "hydrograph") == {}


def test_a_redraw_keeps_a_cmap_the_run_chose() -> None:
    run = _SealedRun({"cmap": "cividis"})

    assert figure_options_from_run(run, "seepage_map") == {"cmap": "cividis"}


def test_a_redraw_of_a_run_without_snapshot_takes_the_figure_defaults() -> None:
    assert figure_options_from_run(_SealedRun(None), "seepage_map") == {}


def test_a_redraw_reads_the_former_timestep_of_an_old_snapshot_silently() -> None:
    run = _SealedRun({"overrides": {"seepage_map": {"timestep": 33}}})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert figure_options_from_run(run, "seepage_map") == {"time": 33}
