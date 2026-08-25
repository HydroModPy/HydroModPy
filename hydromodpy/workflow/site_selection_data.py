"""Data-layer adapters used by site-selection workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.variables.dem.config import DemConfig
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig

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
        data_root=_default_data_root(workspace_root=workspace_root, data_root=data_root),
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
            data_root=_default_data_root(workspace_root=workspace_root, data_root=data_root),
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


def default_site_selection_data_root() -> Path:
    """Default shared data directory for standalone site-selection runs."""

    workspace = os.environ.get("HYDROMODPY_WORKSPACE")
    root = Path(workspace).expanduser() if workspace else Path.home() / "hydromodpy"
    return (root / "data").resolve()


def _default_data_root(
    *,
    workspace_root: str | Path | None,
    data_root: str | Path | None,
) -> Path | None:
    """Use the HydroModPy data workspace when site-selection needs persistence."""

    if data_root is not None:
        return Path(data_root).expanduser().resolve()
    if workspace_root is not None:
        return None
    return default_site_selection_data_root()


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
    "default_site_selection_data_root",
    "load_dem_path",
    "load_hydrometry_records",
]
