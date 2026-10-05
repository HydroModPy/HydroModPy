"""[geographic.crossings] reads the file of [[data.crossings.sources]] when it has no path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher
from hydromodpy.workflow.steps.setup import resolve_crossings_path

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}
_RESOLVER = "hydromodpy.data.variables.crossings.resolver.resolve_crossings_path_from_data_sources"


def _geographic(**crossings) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0,
        y=2.0,
        dem="dem.tif",
        river_network=_RIVER,
        crossings={"enabled": True, **crossings},
    )


def _run_state(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=tmp_path / "project.toml",
        setup=SimpleNamespace(workspace=None),
    )


def _cfg(geographic: GeographicConfig, *, sources: list | None) -> SimpleNamespace:
    crossings = None if sources is None else SimpleNamespace(sources=sources)
    return SimpleNamespace(geographic=geographic, data=SimpleNamespace(crossings=crossings))


def test_the_path_is_filled_from_the_declared_sources(monkeypatch, tmp_path) -> None:
    merged = tmp_path / "crossings_ground_bdtopo_roe_12345678.gpkg"
    calls: list[Path] = []

    def _resolve(cfg, *, config_path, cache_dir=None):
        calls.append(config_path)
        return merged

    monkeypatch.setattr(_RESOLVER, _resolve)
    cfg = _cfg(_geographic(), sources=[SimpleNamespace(source="bdtopo")])

    resolve_crossings_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.crossings.path == merged
    assert calls == [tmp_path / "project.toml"]


def test_a_declared_path_wins_and_nothing_is_resolved(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_RESOLVER, lambda *a, **k: pytest.fail("resolved a declared path"))
    own = tmp_path / "mine.gpkg"
    cfg = _cfg(_geographic(path=own), sources=[SimpleNamespace(source="bdtopo")])

    resolve_crossings_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.crossings.path == own


def test_enabled_without_a_path_and_without_a_source_is_refused(tmp_path) -> None:
    for sources in (None, []):
        cfg = _cfg(_geographic(), sources=sources)

        with pytest.raises(ConfigError, match=r"crossings"):
            resolve_crossings_path(cfg, _run_state(tmp_path))


def test_a_disabled_notch_resolves_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_RESOLVER, lambda *a, **k: pytest.fail("resolved a disabled notch"))
    geographic = GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif")
    cfg = _cfg(geographic, sources=[SimpleNamespace(source="bdtopo")])

    resolve_crossings_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.crossings.path is None


def _overview(tmp_path: Path, cfg: SimpleNamespace) -> tuple[DataOverviewLauncher, SimpleNamespace]:
    pipeline = object.__new__(DataOverviewLauncher)
    pipeline.config_path = tmp_path / "project.toml"
    return pipeline, SimpleNamespace(cfg=cfg, workspace=None)


def test_the_overview_fills_the_path_the_same_way(monkeypatch, tmp_path) -> None:
    merged = tmp_path / "crossings_ground_roe_abcdef01.gpkg"
    monkeypatch.setattr(_RESOLVER, lambda cfg, *, config_path, cache_dir=None: merged)
    cfg = _cfg(_geographic(), sources=[SimpleNamespace(source="roe")])
    pipeline, state = _overview(tmp_path, cfg)

    pipeline._bootstrap_crossings(state)

    assert cfg.geographic.crossings.path == merged


def test_the_overview_refuses_a_notch_with_no_structures(tmp_path) -> None:
    cfg = _cfg(_geographic(), sources=None)
    pipeline, state = _overview(tmp_path, cfg)

    with pytest.raises(ConfigMissingError, match=r"crossings"):
        pipeline._bootstrap_crossings(state)


# --- the bed regularisation reads the declared weirs and dams -----------------


def _bed_only() -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0,
        y=2.0,
        dem="dem.tif",
        river_network=_RIVER,
        bed_regularization={"enabled": True},
    )


def test_the_bed_regularisation_fills_the_path_with_the_notch_off(monkeypatch, tmp_path) -> None:
    merged = tmp_path / "crossings_ground_roe_12345678.gpkg"
    monkeypatch.setattr(_RESOLVER, lambda cfg, *, config_path, cache_dir=None: merged)
    run_cfg = _cfg(_bed_only(), sources=[SimpleNamespace(source="roe")])
    overview_cfg = _cfg(_bed_only(), sources=[SimpleNamespace(source="roe")])
    pipeline, state = _overview(tmp_path, overview_cfg)

    resolve_crossings_path(run_cfg, _run_state(tmp_path))
    pipeline._bootstrap_crossings(state)

    for cfg in (run_cfg, overview_cfg):
        assert cfg.geographic.crossings.path == merged
        assert not cfg.geographic.crossings.enabled


def test_the_bed_regularisation_without_a_source_resolves_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_RESOLVER, lambda *a, **k: pytest.fail("resolved without a source"))
    for sources in (None, []):
        cfg = _cfg(_bed_only(), sources=sources)
        pipeline, state = _overview(tmp_path, cfg)

        resolve_crossings_path(cfg, _run_state(tmp_path))
        pipeline._bootstrap_crossings(state)

        assert cfg.geographic.crossings.path is None
