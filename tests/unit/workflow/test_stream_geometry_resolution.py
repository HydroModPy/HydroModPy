"""Wire the burn network from ``[data.hydrography]`` before the geographic step."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.data.variables.hydrography.resolver as hydrography_resolver
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.steps.setup import resolve_stream_geometry_path


def _run_state(tmp_path: Path) -> Any:
    workspace = SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data"))
    return SimpleNamespace(
        config_path=tmp_path / "project.toml",
        setup=SimpleNamespace(workspace=workspace),
    )


def _cfg(*, enabled=True, declared=None, sources=(), synthetic=False) -> Any:
    enforce = SimpleNamespace(enabled=enabled, stream_geometry_path=declared)
    return SimpleNamespace(
        geographic=SimpleNamespace(
            enforce_streams=enforce,
            uses_synthetic_geographic=lambda: synthetic,
        ),
        data=SimpleNamespace(hydrography=SimpleNamespace(sources=list(sources))),
    )


def _custom(path):
    return SimpleNamespace(source="custom", path=str(path), force_refresh=False)


def test_the_network_declared_by_the_data_family_fills_the_burn(tmp_path, monkeypatch):
    network = tmp_path / "network.gpkg"
    network.touch()
    cfg = _cfg(sources=[_custom(network)])
    monkeypatch.setattr(
        hydrography_resolver,
        "resolve_stream_geometry_path_from_data_sources",
        lambda *_args, **_kwargs: network,
    )

    resolve_stream_geometry_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.enforce_streams.stream_geometry_path == network


def test_an_explicitly_declared_network_wins(tmp_path):
    declared = tmp_path / "declared.gpkg"
    other = tmp_path / "other.gpkg"
    other.touch()
    cfg = _cfg(declared=declared, sources=[_custom(other)])

    resolve_stream_geometry_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.enforce_streams.stream_geometry_path == declared


def test_a_disabled_burn_is_left_alone(tmp_path):
    other = tmp_path / "other.gpkg"
    other.touch()
    cfg = _cfg(enabled=False, sources=[_custom(other)])

    resolve_stream_geometry_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.enforce_streams.stream_geometry_path is None


def test_no_hydrography_source_leaves_the_burn_to_raise_its_own_error(tmp_path):
    """The burn names the file it cannot read; this step must not pre-empt it."""
    cfg = _cfg(sources=[])

    resolve_stream_geometry_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.enforce_streams.stream_geometry_path is None


def test_a_synthetic_geographic_is_left_alone(tmp_path):
    other = tmp_path / "other.gpkg"
    other.touch()
    cfg = _cfg(synthetic=True, sources=[_custom(other)])

    resolve_stream_geometry_path(cfg, _run_state(tmp_path))

    assert cfg.geographic.enforce_streams.stream_geometry_path is None


def test_a_source_holding_no_vector_is_reported(tmp_path, monkeypatch):
    raster = tmp_path / "network.tif"
    raster.touch()
    cfg = _cfg(sources=[_custom(raster)])
    monkeypatch.setattr(
        hydrography_resolver,
        "resolve_stream_geometry_path_from_data_sources",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ConfigError, match="a raster one cannot be burned"):
        resolve_stream_geometry_path(cfg, _run_state(tmp_path))
