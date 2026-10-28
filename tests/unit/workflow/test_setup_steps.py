"""[geographic.crossings] reads the file of [[data.crossings.sources]] when it has no path.

The run setup and the data overview resolve it with the same rule: when the
notch or the bed regularisation is on, and never over a declared path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher
from hydromodpy.workflow.steps.setup import resolve_crossings_path
from tests._helpers.geographic_cases import BENCH_RIVER

_RESOLVER = "hydromodpy.data.variables.crossings.resolver.resolve_crossings_path_from_data_sources"
_ROE = [SimpleNamespace(source="roe")]


def _geographic(section: str = "crossings", **crossings) -> GeographicConfig:
    sections = {"crossings": {"enabled": True, **crossings}}
    if section == "bed":
        sections = {"bed_regularization": {"enabled": True}}
    elif section == "off":
        sections = {}
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", river_network=BENCH_RIVER, **sections
    )


def _cfg(geographic: GeographicConfig, sources: list | None) -> SimpleNamespace:
    crossings = None if sources is None else SimpleNamespace(sources=sources)
    return SimpleNamespace(geographic=geographic, data=SimpleNamespace(crossings=crossings))


def _resolve(entry: str, cfg: SimpleNamespace, tmp_path: Path) -> None:
    """Resolve the path as the run setup or as the data overview does."""
    if entry == "run":
        state = SimpleNamespace(
            config_path=tmp_path / "project.toml", setup=SimpleNamespace(workspace=None)
        )
        resolve_crossings_path(cfg, state)
        return
    overview = object.__new__(DataOverviewLauncher)
    overview.config_path = tmp_path / "project.toml"
    overview._bootstrap_crossings(SimpleNamespace(cfg=cfg, workspace=None))


def _forbid(monkeypatch) -> None:
    monkeypatch.setattr(_RESOLVER, lambda *a, **k: pytest.fail("resolved a path"))


@pytest.mark.parametrize("entry", ["run", "overview"])
@pytest.mark.parametrize("section", ["crossings", "bed"])
def test_the_path_is_filled_from_the_declared_sources(entry, section, monkeypatch, tmp_path):
    merged = tmp_path / "crossings_ground_roe_12345678.gpkg"
    calls: list[Path] = []

    def resolve(cfg, *, config_path, cache_dir=None):
        calls.append(config_path)
        return merged

    monkeypatch.setattr(_RESOLVER, resolve)
    cfg = _cfg(_geographic(section), _ROE)

    _resolve(entry, cfg, tmp_path)

    assert cfg.geographic.crossings.path == merged
    assert cfg.geographic.crossings.enabled is (section == "crossings")
    assert calls == [tmp_path / "project.toml"]


@pytest.mark.parametrize("entry", ["run", "overview"])
def test_a_declared_path_wins_and_a_notch_that_is_off_resolves_nothing(
    entry, monkeypatch, tmp_path
) -> None:
    _forbid(monkeypatch)
    own = _cfg(_geographic(path=tmp_path / "mine.gpkg"), _ROE)
    off = _cfg(_geographic("off"), _ROE)

    for cfg in (own, off):
        _resolve(entry, cfg, tmp_path)

    assert own.geographic.crossings.path == tmp_path / "mine.gpkg"
    assert off.geographic.crossings.path is None


@pytest.mark.parametrize(
    ("entry", "sources", "error"),
    [("run", None, ConfigError), ("run", [], ConfigError), ("overview", None, ConfigMissingError)],
)
def test_a_notch_with_no_path_and_no_source_is_refused(entry, sources, error, tmp_path) -> None:
    with pytest.raises(error, match=r"crossings"):
        _resolve(entry, _cfg(_geographic(), sources), tmp_path)


@pytest.mark.parametrize("entry", ["run", "overview"])
@pytest.mark.parametrize("sources", [None, []])
def test_the_bed_regularisation_without_a_source_fits_without_cuts(
    entry, sources, monkeypatch, tmp_path
) -> None:
    _forbid(monkeypatch)
    cfg = _cfg(_geographic("bed"), sources)

    _resolve(entry, cfg, tmp_path)

    assert cfg.geographic.crossings.path is None
