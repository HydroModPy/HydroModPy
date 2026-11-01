"""Data-layer adapters of the site-selection runner: hydrometry records and the DEM file."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from hydromodpy.core.exceptions import ConfigMissingError, DataContractViolation
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.data import DataStore
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.dem.config import DemConfig
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.site_selection.config.site_selection_config import (
    SiteSelectionConfig,
    SiteSelectionFile,
)
from hydromodpy.workflow.site_selection.config_paths import resolve_optional_path, resolve_paths

HydrometryLoader = Callable[..., list[PointRecord]]
DemLoader = Callable[..., list[FieldRecord]]


def load_hydrometry_records(
    config: HydrometryConfig,
    *,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_extent: tuple | None = None,
    project_period: tuple[datetime, datetime] | None = None,
    loader: HydrometryLoader | None = None,
) -> list[PointRecord]:
    """Load hydrometry records through the existing data manager stack."""

    period = project_period or _period_from_config(config)
    if loader is not None:
        return loader(
            config=config,
            workspace_root=workspace_root,
            data_root=data_root,
            project_extent=project_extent,
            project_period=period,
        )

    store = DataStore(
        workspace_root=workspace_root,
        data_root=_resolved(data_root),
        project_extent=project_extent,
        project_period=period,
    )
    return list(store.load_hydrometry(config).points)


def load_dem_path(
    config: DemConfig,
    *,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_extent: tuple | None = None,
    loader: DemLoader | None = None,
) -> Path:
    """Load a DEM through the existing data manager stack and return its file path."""

    resolved_config = _with_project_extent(config, project_extent=project_extent)
    if loader is not None:
        fields = loader(
            config=resolved_config,
            workspace_root=workspace_root,
            data_root=data_root,
            project_extent=project_extent,
        )
    else:
        store = DataStore(
            workspace_root=workspace_root,
            data_root=_resolved(data_root),
            project_extent=project_extent,
        )
        fields = list(
            store.load_dem(
                resolved_config,
                project_extent=project_extent,
            ).fields
        )

    if not fields:
        raise DataContractViolation("DEM data manager did not return any field record.")
    data = fields[0].data
    if not isinstance(data, (str, Path)):
        raise DataContractViolation(
            "DEM data manager returned an in-memory field; a file path is required."
        )
    path = Path(data).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"DEM data manager returned a missing path: {path}")
    return path


def _with_project_extent(
    config: DemConfig,
    *,
    project_extent: tuple | None,
) -> DemConfig:
    """Ask bbox-capable DEM API sources to use the explicit project extent."""

    if project_extent is None:
        return config
    sources = []
    changed = False
    for source in config.sources:
        if (
            getattr(source, "source", None) == "ign_geoplateforme_dem"
            and getattr(source, "mask_path", None) is None
            and getattr(source, "extent", None) is None
        ):
            source = source.model_copy(update={"extent": "study_area"})
            changed = True
        sources.append(source)
    if not changed:
        return config
    return config.model_copy(update={"sources": sources})


def _resolved(data_root: str | Path | None) -> Path | None:
    """Return the data root a selection names, or None to load without a cache."""

    return None if data_root is None else Path(data_root).expanduser().resolve()


def _period_from_config(config: HydrometryConfig) -> tuple[datetime, datetime] | None:
    if config.date_start and config.date_end:
        return (
            datetime.fromisoformat(config.date_start),
            datetime.fromisoformat(config.date_end),
        )
    return None


__all__ = [
    "DemLoader",
    "HydrometryLoader",
    "load_dem_path",
    "load_hydrometry_records",
    "load_hydrometry_config_for_site_selection",
    "load_site_selection_config",
]


def load_site_selection_config(path: str | Path) -> SiteSelectionConfig:
    """Load and validate the ``[site_selection]`` section of a TOML file."""

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    section = raw.get("site_selection")
    if not isinstance(section, dict):
        raise ConfigMissingError("TOML file must contain a [site_selection] section.")
    cfg = SiteSelectionFile.model_validate({"site_selection": section}).site_selection
    return resolve_paths(cfg, base_dir=config_path.parent)


def load_hydrometry_config_for_site_selection(path: str | Path) -> HydrometryConfig:
    """Load a companion ``[hydrometry]`` section for observation-led selection."""

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    section = raw.get("hydrometry")
    if not isinstance(section, dict):
        raise ConfigMissingError("TOML file must contain a [hydrometry] section.")
    cfg = HydrometryConfig.model_validate(section)
    sources = []
    for source in cfg.sources:
        source_path = getattr(source, "path", None)
        if source_path is not None:
            source = source.model_copy(
                update={"path": resolve_optional_path(source_path, base_dir=config_path.parent)}
            )
        sources.append(source)
    return cfg.model_copy(update={"sources": sources})
