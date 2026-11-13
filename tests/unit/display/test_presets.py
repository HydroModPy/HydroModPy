"""The shipped presets expand, draw by name, fill their holes and refuse the rest."""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import figure_registry
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import (
    DRAW_KEYWORDS,
    SPECIALS,
    WIDTHS_MM,
    FigureRequest,
    expand,
    is_registered,
)
from hydromodpy.project.show import takes_request
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.stream_network import cell_fields
from hydromodpy.results.run.group import RunSet
from tests._helpers.run_builders import GAUGE

from ._calibration_journal import K_BOUNDS, journal_session
from .test_special_calibration import rows
from .test_special_lake import lake_run
from .test_special_series import write_daily

PANELS = ("hydrograph", "residuals", "water_budget", "watershed_id_card", "network_expansion")


@pytest.mark.parametrize("name", PRESETS)
def test_every_preset_expands_to_existing_variables_or_to_its_module(name):
    figure = expand(FigureRequest(preset=name), PRESETS)
    if name in PANELS:
        assert figure.draw is None and len(figure.panels) == 2
        return
    assert figure.special == name and figure.draw is None


@pytest.mark.parametrize("name", SPECIALS)
def test_the_row_of_a_special_agrees_with_its_module(name):
    row = SPECIALS[name]
    draw = importlib.import_module(f"hydromodpy.display.special.{name}").draw
    declared = [key for key in inspect.signature(draw).parameters if key in DRAW_KEYWORDS]
    assert sorted(declared) == sorted(row.keywords)
    assert row.subject in ("run", "session", "runset") and row.width in (*WIDTHS_MM, None)
    assert all(is_registered(variable) for variable in row.variables)


@pytest.mark.allow_subprocess
def test_a_config_that_names_a_special_loads_neither_matplotlib_nor_pandas():
    code = (
        "import sys\nfrom hydromodpy.display.config import DisplayConfig\n"
        "DisplayConfig.model_validate({'figure': [{'preset': 'recession'}]})\n"
        "print(sorted({'matplotlib', 'pandas'} & set(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_a_preset_takes_its_name_from_its_key():
    assert all(request.name == key for key, request in PRESETS.items())


def test_there_are_five_panel_presets_and_twelve_specials():
    assert (len(PANELS), len(SPECIALS), len(PRESETS)) == (5, 12, 17)


@pytest.mark.parametrize("name", PANELS)
def test_a_panel_preset_draws_the_stored_run(stored_run, name, monkeypatch):
    if name == "network_expansion":  # the stored run holds no network, so give it the cells
        flowing = np.zeros((4, 12))
        flowing[:, 0] = 1.0
        monkeypatch.setattr(cell_fields, "rebuilt_unavailable", lambda run, field: None)
        monkeypatch.setattr(cell_fields, "rebuilt_rows", lambda run, field, steps: flowing[steps])
    assert len(stored_run.figure(name).axes) >= 2


def test_a_hole_is_filled_and_a_field_that_is_no_hole_is_refused(stored_run):
    tables = stored_run.figure_data("hydrograph", variable="discharge", station=GAUGE)
    assert set(tables) == {"a", "b"}
    with pytest.raises(ValueError, match="no hole 'layer'"):
        stored_run.figure("hydrograph", layer=1)
    with pytest.raises(ValueError, match="takes no option normalize.*variable, station"):
        stored_run.figure("hydrograph", normalize=True)
    with pytest.raises(ValueError, match='To replace log_y, write scale = "log"'):
        stored_run.figure("hydrograph", log_y=True)
    with pytest.raises(
        ValueError, match="'sfr_longitudinal_profile' takes no option station.*time"
    ):
        stored_run.figure("sfr_longitudinal_profile", station="x")
    with pytest.raises(DisplayError, match="special figure.*no table of numbers"):
        stored_run.figure_data("recession")


@pytest.mark.parametrize("name", ["hydrograph", "recession"])
def test_a_name_both_paths_know_draws_the_preset_by_door_and_the_registered_figure_by_key(name):
    assert takes_request(name, PRESETS, {}) and figure_registry.get(name).spec.name == name


def test_specials_are_reached_by_name_on_a_run_a_session_and_a_set(tmp_path):
    assert lake_run(tmp_path / "lake").figure("lake_abacus_comparison").axes
    journal_session(
        tmp_path / "cal", rows({"K": [1e-5, 2e-5, 4e-5, 8e-5]}), bounds=K_BOUNDS, best_trial=3
    )
    session = hmp.open(tmp_path / "cal").sessions["calibration"]
    assert session.figure("calibration_progress").axes
    for name in ("a", "b"):
        write_daily(tmp_path / "set", name, (1.0 + 0.02 * np.arange(60)) ** -2.0)
    rebuild_index(tmp_path / "set")
    store = hmp.open(tmp_path / "set").store
    assert RunSet([store[n].sim_id for n in "ab"], store).figure("ensemble_band").axes
    assert store["a"].figure("recession").axes
    with pytest.raises(DisplayError, match="draws a run, not a session"):
        session.figure("recession")
    with pytest.raises(DisplayError, match="draws a calibration session.*not promoted"):
        store["a"].figure("calibration_progress")
    with pytest.raises(DisplayError, match="draws a runset, not a run"):
        store["a"].figure("ensemble_band")
