"""The steady initial-condition solve reads the listing MF6 wrote, whatever the run name.

MF6 names the listing after the safe model name, which is lowercase. The head file
keeps the output stem. A reader that built the listing name from the output stem
looked for a file that did not exist as soon as the two differed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import mf6_safe_name
from hydromodpy.solver.modflow6.support import steady_initial_conditions as ssic

CLOSED_LISTING = " PERCENT DISCREPANCY =  0.00     PERCENT DISCREPANCY =  0.00\n"


def test_the_listing_is_named_after_the_safe_model_name(tmp_path: Path) -> None:
    model = SimpleNamespace(
        model_name="Nancon Lake_A",
        model_name_mf6=mf6_safe_name("Nancon Lake_A"),
        model_output_name="Nancon Lake_A",
        full_path=str(tmp_path),
    )
    (tmp_path / "nancon_lake_a.lst").write_text(CLOSED_LISTING)

    assert ssic._model_listing_path(model).is_file()


def test_a_name_with_a_capital_letter_reaches_the_safe_name_without_the_attribute(
    tmp_path: Path,
) -> None:
    model = SimpleNamespace(model_name="Run One", full_path=str(tmp_path))

    assert ssic._model_listing_path(model) == tmp_path / "run_one.lst"


class _StubMF6:
    """Names its files the way the MF6 wrapper does and writes a closed, unconverged solve."""

    nlay = 1
    ncpl = 2
    exe = "mf6"

    def __init__(self, *, model_folder, model_name, **_kwargs) -> None:
        self.model_name = model_name
        self.model_name_mf6 = mf6_safe_name(model_name)
        self.model_output_name = model_name
        self.full_path = str(Path(model_folder) / model_name)
        self.auxiliary = False
        self.geographic = None
        self.modflow_config = None
        self.flow = SimpleNamespace()
        self.domain = None
        self.runtime_cell_mesh = None
        self.time_grid = None
        self.preprocess_options = SimpleNamespace()

    def pre_processing(self, **_kwargs) -> None:
        Path(self.full_path).mkdir(parents=True, exist_ok=True)

    def processing(self, _options) -> bool:
        # MF6 stopped short of convergence; its listing carries a closed budget.
        (Path(self.full_path) / f"{self.model_name_mf6}.lst").write_text(CLOSED_LISTING)
        return False


def test_a_run_named_with_capitals_still_finds_the_listing(monkeypatch, tmp_path) -> None:
    """The listing the solve wrote is the one the acceptance reads, so no RuntimeError."""
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "steady_flow_copy_for_initialization", lambda flow: flow)
    monkeypatch.setattr(ssic, "_compact_flow_forcings_to_one_period", lambda *_a: 0)
    monkeypatch.setattr(ssic, "single_period_mean_forcing_time_grid", lambda grid: grid)
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    parent = _StubMF6(model_folder=tmp_path, model_name="Run With Capitals")

    with pytest.warns(RuntimeWarning, match="final water budget is closed"):
        head = ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    assert head.shape == (1, 2)
