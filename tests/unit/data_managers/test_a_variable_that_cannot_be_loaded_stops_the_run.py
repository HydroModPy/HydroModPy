"""A declared variable that cannot be loaded stops the run with a typed error.

The second phase of ``load_all`` used to log ``Load of '<variable>' failed`` and
go on: a run without its gauge or its forcing, with exit code 0. Only a type the
planner inferred, under ``data.inference_mode = "warn"``, may still be dropped,
and the warning names it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.core.exceptions import (
    ConfigMissingError,
    DataError,
    DataSourceError,
    StepError,
)
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.loading.plan import DataLoadPlan


def _loader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan: DataLoadPlan,
    cause: Exception,
) -> DataManagersRuntimeLoader:
    loader = DataManagersRuntimeLoader(config_path=tmp_path / "project.toml", data_plan=plan)
    monkeypatch.setattr(loader, "_init_catalog", lambda paths: None)
    monkeypatch.setattr(loader, "_workspace_paths", lambda result: None)

    def failing_load(result, variable: str) -> None:
        try:
            raise cause
        except Exception as exc:
            loader._handle_data_loading_error(result, variable, exc)

    monkeypatch.setattr(loader, "_load_generic_variable", failing_load)
    return loader


def _context(inference_mode: str = "warn") -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(data=SimpleNamespace(inference_mode=inference_mode)),
        loaded_data=SimpleNamespace(),
    )


@pytest.mark.fast
def test_a_declared_series_that_fails_to_load_raises_a_data_error(monkeypatch, tmp_path):
    plan = DataLoadPlan(explicit_types=("hydrometry",))
    loader = _loader(monkeypatch, tmp_path, plan, RuntimeError("Hub'Eau did not answer"))

    with pytest.raises(DataError, match="hydrometry.*Hub'Eau did not answer") as info:
        loader.load_all(_context())

    assert exit_code_for(info.value) == EXIT_VALIDATION


@pytest.mark.fast
def test_the_typed_cause_keeps_its_class(monkeypatch, tmp_path):
    plan = DataLoadPlan(explicit_types=("hydrometry",))
    loader = _loader(monkeypatch, tmp_path, plan, DataSourceError("refused"))

    with pytest.raises(DataSourceError, match="'hydrometry': refused"):
        loader.load_all(_context())


@pytest.mark.fast
def test_a_missing_file_exits_as_not_found(monkeypatch, tmp_path):
    plan = DataLoadPlan(explicit_types=("recharge",))
    loader = _loader(monkeypatch, tmp_path, plan, FileNotFoundError("recharge.nc"))

    with pytest.raises(FileNotFoundError, match="'recharge'") as info:
        loader.load_all(_context())

    assert exit_code_for(info.value) == EXIT_NOT_FOUND


@pytest.mark.fast
def test_an_inferred_type_under_warn_is_dropped_by_name(monkeypatch, tmp_path, caplog):
    plan = DataLoadPlan(explicit_types=(), inferred_types=("lake_inflow",))
    loader = _loader(monkeypatch, tmp_path, plan, RuntimeError("no file"))

    with caplog.at_level(logging.WARNING):
        loader.load_all(_context("warn"))

    assert "The run goes on without 'lake_inflow'" in caplog.text


@pytest.mark.fast
def test_a_declared_type_without_its_section_is_a_missing_config(tmp_path):
    loader = DataManagersRuntimeLoader(
        config_path=tmp_path / "project.toml",
        data_plan=DataLoadPlan(explicit_types=("hydrometry",)),
    )

    with pytest.raises(ConfigMissingError, match=r"missing \[data.hydrometry\]") as info:
        loader._handle_missing_data_section(
            _context(), "hydrometry", "missing [data.hydrometry] section"
        )

    assert exit_code_for(info.value) == EXIT_CONFIG


@pytest.mark.fast
def test_config_check_refuses_a_listed_type_without_its_section(tmp_path):
    with pytest.raises(ValueError, match=r"lists 'hydrometry'.*no \[data.hydrometry\]"):
        DataManagersConfig.from_toml_section({"types": ["hydrometry"]}, base_dir=tmp_path)


@pytest.mark.fast
def test_geology_listed_alone_still_takes_its_default_section(tmp_path):
    config = DataManagersConfig.from_toml_section({"types": ["geology"]}, base_dir=tmp_path)

    assert config.geology is not None


@pytest.mark.fast
def test_a_failed_step_exits_with_the_code_of_its_cause():
    wrapped = StepError("load_data", DataError("Failed to load data manager 'etp'"))

    assert exit_code_for(wrapped) == EXIT_VALIDATION
