"""The data loader: one store on the data folder, the time window of each variable, the optional
geology domain, and the typed errors of a variable that cannot be loaded.

A declared variable that cannot be loaded stops the run. Only a type the planner inferred,
under ``data.inference_mode = "warn"``, may be dropped, and the warning names it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import (
    ConfigMissingError,
    DataError,
    DataSourceError,
    StepError,
)
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.loader import DataLoader
from hydromodpy.data.loading.plan import DataLoadPlan

SIM_WINDOW = ("2020-01-01", "2020-01-31")


def _context(inference_mode: str = "warn") -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(data=SimpleNamespace(inference_mode=inference_mode)),
        loaded_data=SimpleNamespace(),
    )


def _loader(tmp_path: Path, plan: DataLoadPlan | None = None) -> DataLoader:
    return DataLoader(config_path=tmp_path / "project.toml", data_plan=plan or DataLoadPlan())


def _failing_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, plan: DataLoadPlan, cause: Exception
) -> DataLoader:
    loader = _loader(tmp_path, plan)
    monkeypatch.setattr(loader, "_init_store", lambda paths: None)
    monkeypatch.setattr(loader, "_workspace_paths", lambda result: None)

    def failing_load(result, variable: str) -> None:
        try:
            raise cause
        except Exception as exc:
            loader._handle_data_loading_error(result, variable, exc)

    monkeypatch.setattr(loader, "_load_generic_variable", failing_load)
    return loader


def _windowed_loader(tmp_path: Path, window: tuple[str, str] | None) -> DataLoader:
    loader = _loader(tmp_path)
    loader._resolve_simulation_time_window_dates = lambda result: window  # noqa: ARG005
    return loader


def _ctx(**kwargs: Any) -> WorkflowContext:
    return cast(WorkflowContext, SimpleNamespace(**kwargs))


def _paths(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(root=tmp_path / "ws", data_dir=tmp_path / "ws" / "data")


def test_the_store_is_made_once(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    loader._init_store(_paths(tmp_path))
    first = loader._require_store()

    loader._init_store(_paths(tmp_path))

    assert loader._require_store() is first


def test_a_run_leaves_no_database_in_the_data_folder(tmp_path: Path) -> None:
    loader = _loader(tmp_path)
    paths = _paths(tmp_path)

    loader._init_store(paths)
    loader._require_store().index.rows()

    assert list(paths.data_dir.iterdir()) == []


# A declared type that fails to load: its cause, the error that stops the run, its exit code.
LOAD_FAILURES = [
    pytest.param(
        "hydrometry",
        RuntimeError("Hub'Eau did not answer"),
        DataError,
        "hydrometry.*Hub'Eau did not answer",
        EXIT_VALIDATION,
        id="series that fails",
    ),
    pytest.param(
        "hydrometry",
        DataSourceError("refused"),
        DataSourceError,
        "'hydrometry': refused",
        EXIT_VALIDATION,
        id="typed cause keeps its class",
    ),
    pytest.param(
        "recharge",
        FileNotFoundError("recharge.nc"),
        FileNotFoundError,
        "'recharge'",
        EXIT_NOT_FOUND,
        id="missing file",
    ),
]


@pytest.mark.fast
@pytest.mark.parametrize(("variable", "cause", "error", "said", "exit_code"), LOAD_FAILURES)
def test_a_declared_variable_that_fails_stops_the_run(
    monkeypatch, tmp_path, variable, cause, error, said, exit_code
):
    plan = DataLoadPlan(explicit_types=(variable,))
    loader = _failing_loader(monkeypatch, tmp_path, plan, cause)

    with pytest.raises(error, match=said) as info:
        loader.load_all(_context())

    assert exit_code_for(info.value) == exit_code


@pytest.mark.fast
def test_an_inferred_type_under_warn_is_dropped_by_name(monkeypatch, tmp_path, caplog):
    plan = DataLoadPlan(explicit_types=(), inferred_types=("lake_inflow",))
    loader = _failing_loader(monkeypatch, tmp_path, plan, RuntimeError("no file"))

    with caplog.at_level(logging.WARNING):
        loader.load_all(_context("warn"))

    assert "The run goes on without 'lake_inflow'" in caplog.text


@pytest.mark.fast
def test_a_declared_type_without_its_section_is_a_missing_config(tmp_path):
    loader = _loader(tmp_path, DataLoadPlan(explicit_types=("hydrometry",)))

    with pytest.raises(ConfigMissingError, match=r"missing \[data.hydrometry\]") as info:
        loader._handle_missing_data_section(
            _context(), "hydrometry", "missing [data.hydrometry] section"
        )

    assert exit_code_for(info.value) == EXIT_CONFIG


@pytest.mark.fast
def test_a_failed_step_exits_with_the_code_of_its_cause():
    wrapped = StepError("load_data", DataError("Failed to load data manager 'etp'"))

    assert exit_code_for(wrapped) == EXIT_VALIDATION


# The section keeps what it declares, or inherits the simulation window as strings.
SECTION_WINDOWS = [
    pytest.param(
        SIM_WINDOW,
        {"sources": [], "date_start": "2020-01-01", "date_end": "2020-01-31"},
        id="inherits the simulation window",
    ),
    pytest.param(None, {"sources": []}, id="no simulation window"),
]


@pytest.mark.parametrize(("window", "section"), SECTION_WINDOWS)
def test_dates_of_a_section(tmp_path: Path, window, section) -> None:
    loader = _windowed_loader(tmp_path, window)
    given: dict[str, Any] = {"sources": []}

    loader._apply_simulation_window_dates(given, _ctx())

    assert given == section


# Variable spec, overview window of the context (or None), simulation window, period read.
PERIODS = [
    pytest.param(
        "water_quality",
        None,
        SIM_WINDOW,
        (datetime(2020, 1, 1), datetime(2020, 1, 31)),
        id="simulation window first",
    ),
    pytest.param(
        "water_quality",
        SimpleNamespace(date_start="1999-01-01", date_end="1999-12-31"),
        None,
        (datetime(1999, 1, 1), datetime(1999, 12, 31)),
        id="overview window last",
    ),
    pytest.param("recharge", None, SIM_WINDOW, None, id="config spec without dates"),
]


@pytest.mark.parametrize(("spec", "overview", "window", "period"), PERIODS)
def test_period_of_a_spec(tmp_path: Path, spec, overview, window, period) -> None:
    loader = _windowed_loader(tmp_path, window)
    cfg = SimpleNamespace(date_start=None, date_end=None)
    context = _ctx(cfg=SimpleNamespace(overview=overview) if overview else SimpleNamespace())

    assert loader._resolve_period_for_spec(cfg, VARIABLE_SPECS[spec], context) == period


DOMAIN_SUPPORT = object()
GEOGRAPHIC_SUPPORT = object()


def geographic_surface() -> SimpleNamespace:
    return SimpleNamespace(support=GEOGRAPHIC_SUPPORT)


# What the setup holds and the raster support the geology is asked on.
GEOLOGY_SETUPS = [
    pytest.param(
        SimpleNamespace(
            domain=None,
            geographic=SimpleNamespace(get_domain_surface_topo=geographic_surface),
        ),
        GEOGRAPHIC_SUPPORT,
        id="geographic surface when the domain is none",
    ),
    pytest.param(
        SimpleNamespace(
            domain=SimpleNamespace(surface_topo=SimpleNamespace(support=DOMAIN_SUPPORT)),
            geographic=SimpleNamespace(get_domain_surface_topo=geographic_surface),
        ),
        DOMAIN_SUPPORT,
        id="domain surface first",
    ),
    pytest.param(SimpleNamespace(domain=None, geographic=None), None, id="neither"),
]


@pytest.mark.parametrize(("setup", "support"), GEOLOGY_SETUPS)
def test_geology_raster_support(setup, support):
    loader = DataLoader(config_path=__file__, data_plan=DataLoadPlan(explicit_types=("geology",)))

    assert loader._resolve_geology_raster_support(SimpleNamespace(setup=setup)) is support


def test_geology_request_mask_covers_the_buffered_domain_box(tmp_path):
    # Geology is asked over the buffered-box DEM, not the smaller watershed.
    box_dem = tmp_path / "watershed_box_buff_dem.tif"
    box_dem.write_bytes(b"")
    geographic = SimpleNamespace(
        watershed_box_buff_dem=str(box_dem),
        watershed_shp=str(tmp_path / "watershed.shp"),
    )

    assert DataLoader._geology_request_mask(geographic) == box_dem


def test_geology_request_mask_falls_back_to_the_watershed(tmp_path):
    # Without a buffered-box DEM on disk the watershed polygon is used.
    geographic = SimpleNamespace(
        watershed_box_buff_dem=str(tmp_path / "absent.tif"),
        watershed_shp=str(tmp_path / "watershed.shp"),
    )

    assert DataLoader._geology_request_mask(geographic) == (tmp_path / "watershed.shp")
