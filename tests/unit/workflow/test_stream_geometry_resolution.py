"""Hand the network map of ``[data.hydrography]`` to the geographic step, for alpha only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import hydromodpy.data.variables.hydrography.resolver as hydrography_resolver
from hydromodpy.workflow.steps.setup import resolve_network_map_path


def _run_state(tmp_path: Path, *, config_path: Path | None = None) -> Any:
    return SimpleNamespace(config_path=config_path or tmp_path / "project.toml")


def _cfg(*, sources=(), synthetic=False) -> Any:
    return SimpleNamespace(
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: synthetic),
        data=SimpleNamespace(hydrography=SimpleNamespace(sources=list(sources))),
    )


def _custom(path):
    return SimpleNamespace(source="custom", path=str(path), force_refresh=False)


def test_the_network_declared_by_the_data_family_is_the_map_of_alpha(tmp_path, monkeypatch):
    network = tmp_path / "network.gpkg"
    network.touch()
    cfg = _cfg(sources=[_custom(network)])
    monkeypatch.setattr(
        hydrography_resolver,
        "resolve_network_map_path",
        lambda *_args, **_kwargs: network,
    )

    assert resolve_network_map_path(cfg, _run_state(tmp_path)) == network


def test_the_map_never_enters_the_configuration(tmp_path):
    network = tmp_path / "network.gpkg"
    network.touch()
    cfg = _cfg(sources=[_custom(network)])

    resolve_network_map_path(cfg, _run_state(tmp_path))

    assert vars(cfg.geographic).keys() == {"uses_synthetic_geographic"}


def test_no_hydrography_source_means_alpha_does_not_run(tmp_path):
    assert resolve_network_map_path(_cfg(sources=[]), _run_state(tmp_path)) is None


def test_a_synthetic_geographic_is_left_alone(tmp_path):
    other = tmp_path / "other.gpkg"
    other.touch()
    cfg = _cfg(synthetic=True, sources=[_custom(other)])

    assert resolve_network_map_path(cfg, _run_state(tmp_path)) is None


def test_a_source_holding_no_vector_resolves_to_nothing_without_raising(tmp_path):
    raster = tmp_path / "network.tif"
    raster.touch()
    cfg = _cfg(sources=[_custom(raster)])

    assert resolve_network_map_path(cfg, _run_state(tmp_path)) is None


def test_an_api_source_resolves_to_nothing(tmp_path):
    cfg = _cfg(sources=[SimpleNamespace(source="osm", path=None, force_refresh=False)])

    assert resolve_network_map_path(cfg, _run_state(tmp_path)) is None
