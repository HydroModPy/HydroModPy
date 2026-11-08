"""The MODFLOW-NWT extractor reads what it needs on the ``SolverRun`` and its ``Retention``.

The dry-cell sentinels come from the options of the run, the start date and the
vertical layout from its ``Model``, and the per-cell budget terms from the
retention. Nothing is asked of the configuration or of the workflow, so a run
read back from a resume extracts as a run that was just solved.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.fields.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
)
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow_nwt.extractors import flow as nwt_flow
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.model_factory import make_model, small_geometry, time_grid
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run

HDRY, HNOFLO = -100.0, -9999.0


class _Store:
    """A store that keeps the heads and the time axis it is asked to write."""

    sim_id = "sim-1"
    save_zarr = False

    def __init__(self) -> None:
        self.heads: np.ndarray | None = None
        self.time: np.ndarray | None = None

    def write_time(self, sim_id: str, values: Any, **_: Any) -> None:
        self.time = np.asarray(values, dtype=float)

    def write_field_stack(self, sim_id: str, name: str, values: np.ndarray, **_: Any) -> None:
        assert name == "head"
        self.heads = np.asarray(values)


class _Heads:
    """A head file of one period whose three cells hold a sentinel each, and a real head."""

    def __init__(self, path: str) -> None:
        del path

    def get_times(self) -> list[float]:
        return [86400.0]

    def get_kstpkper(self) -> list[tuple[int, int]]:
        return [(0, 0)]

    def get_data(self, totim: float) -> np.ndarray:
        del totim
        return np.array([[[HDRY, HNOFLO, 12.5, -1234.0]]])

    def close(self) -> None:
        pass


@pytest.fixture
def folder(tmp_path: Path, monkeypatch) -> Path:
    """A run folder holding one head file name, read through ``_Heads``."""
    (tmp_path / "flow.hds").write_text("heads")
    monkeypatch.setattr("flopy.utils.binaryfile.HeadFile", _Heads)
    monkeypatch.setattr(nwt_flow, "record_budget_policy", lambda *_args: None)
    return tmp_path


@pytest.fixture
def surface(monkeypatch) -> list[dict]:
    """Record the keywords the extractor gives the writer of the vertical geometry."""
    calls: list[dict] = []
    monkeypatch.setattr(
        ModflowNwtOutputAdapter,
        "_write_surface_elevation",
        lambda self, *args, **kwargs: calls.append(kwargs),
    )
    return calls


def _model(*, layers: dict | None = None, **members: Any):
    """A ``Model`` on a domain, which MODFLOW-NWT requires, whose layers are ``layers``."""
    config = DomainConfig.model_validate({"layers": layers or {}})
    geometry = replace(small_geometry(), domain=SimpleNamespace(config=config))
    return make_model(geometry=geometry, **members)


def _options(**sentinels: dict[str, float]) -> ModflowConfig:
    return ModflowConfig.model_validate({"runtime": sentinels})


@pytest.mark.parametrize(
    ("options", "masked"),
    [
        pytest.param(_options(), (HDRY, HNOFLO), id="the defaults of the backend"),
        pytest.param(
            _options(upw={"hdry": -1234.0}, bas={"hnoflo": -4321.0}),
            (-1234.0, -4321.0),
            id="the sentinels the run was configured with",
        ),
    ],
)
def test_the_sentinels_masked_are_the_ones_of_the_options(
    folder: Path, surface: list[dict], options: ModflowConfig, masked: tuple[float, float]
) -> None:
    store = _Store()

    ModflowNwtOutputAdapter().extract(solved_run(folder, options=options), store, keep_all)

    heads = np.array([HDRY, HNOFLO, 12.5, -1234.0])
    np.testing.assert_array_equal(
        store.heads[0, 0], np.where(np.isin(heads, masked), np.nan, heads)
    )


def test_a_run_without_options_has_no_sentinels_to_read(folder: Path, surface: list[dict]) -> None:
    with pytest.raises(AttributeError):
        ModflowNwtOutputAdapter().extract(solved_run(folder), _Store(), keep_all)


@pytest.mark.parametrize(
    ("layers", "layout"),
    [
        ({"genmtd_lay": "constant", "nlay": 2}, VERTICAL_LAYOUT_COLUMN_FRACTIONS),
        (
            {"genmtd_lay": "surfaces", "layer": [{"name": "a", "depth": 5.0}, {"name": "b"}]},
            VERTICAL_LAYOUT_SURFACES,
        ),
    ],
)
def test_the_layering_of_the_model_reaches_the_geometry_writer(
    folder: Path, surface: list[dict], layers: dict, layout: str
) -> None:
    model = _model(layers=layers)

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=_options(), model=model), _Store(), keep_all
    )

    assert surface == [{"vertical_layout": layout}]


def test_a_run_without_a_model_takes_the_default_layout_and_no_start_date(
    folder: Path, surface: list[dict]
) -> None:
    store = _Store()

    ModflowNwtOutputAdapter().extract(solved_run(folder, options=_options()), store, keep_all)

    assert surface == [{"vertical_layout": VERTICAL_LAYOUT_COLUMN_FRACTIONS}]
    assert store.time is not None and store.time[0] == pytest.approx(86400.0)


def test_the_time_axis_starts_at_the_first_boundary_of_the_model_grid(
    folder: Path, surface: list[dict]
) -> None:
    grid = time_grid(10)
    grid.boundaries = ("2020-01-01", "2020-01-11")
    model = _model(time=ModelTime(grid=grid, regime="transient", first_period_steady=False))
    dated, undated = _Store(), _Store()

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=_options(), model=model), dated, keep_all
    )
    ModflowNwtOutputAdapter().extract(solved_run(folder, options=_options()), undated, keep_all)

    assert dated.time is not None and undated.time is not None
    start = pd.Timestamp("2020-01-01", tz="UTC").timestamp()
    assert dated.time[0] - undated.time[0] == pytest.approx(start)


def test_the_retention_decides_the_per_cell_budget_terms(
    folder: Path, surface: list[dict], monkeypatch
) -> None:
    (folder / "flow.cbc").write_text("budget")
    seen: list[BudgetKeep] = []
    monkeypatch.setattr(
        ModflowNwtOutputAdapter,
        "_extract_budget",
        lambda self, *args, budget_terms, **kwargs: seen.append(budget_terms),
    )
    planned = BudgetKeep.of_terms(("drain",))

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=_options()), _Store(), retention(planned)
    )

    assert seen == [planned]


def test_a_folder_without_a_head_file_is_nothing_there(tmp_path: Path) -> None:
    with pytest.raises(NothingThereError, match="No .hds file"):
        ModflowNwtOutputAdapter().extract(
            solved_run(tmp_path, options=_options()), _Store(), keep_all
        )
