"""Pydantic configuration models for the Data Overview launcher.

Loads only ``[workspace]``, ``[geographic]``, ``[data]``, ``[overview]`` from
the TOML — no ``[simulation]``, ``[flow]``, ``[transport]``, ``[solver]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from hydromodpy.data_managers.data_managers_config import DataManagersConfig
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig


class OverviewPanelsConfig(BaseModel):
    """Toggle individual report panels on/off."""

    map_dem: bool = Field(True, description="DEM elevation map with stations overlay.")
    map_geology: bool = Field(True, description="Geology lithology map.")
    map_hydrography: bool = Field(True, description="River network map with Strahler orders.")
    stats_card: bool = Field(True, description="Key watershed metrics card.")
    timeseries_discharge: bool = Field(True, description="Observed discharge time series.")
    timeseries_piezometry: bool = Field(True, description="Observed piezometric levels time series.")
    climatic_summary: bool = Field(True, description="Mean monthly precipitation and ETP bars.")
    timeseries_intermittency: bool = Field(True, description="ONDE flow-state observations timeline.")
    timeseries_water_quality: bool = Field(True, description="Water quality parameters time series.")
    station_inventory: bool = Field(True, description="Table listing all stations (type, id, coordinates, period).")


class OverviewSection(BaseModel):
    """Overview report settings (watershed identity card)."""

    name: str = Field("", description="Watershed name displayed on report panels. Defaults to workspace catch_name.")
    date_start: str | None = Field(None, description="Global start date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    date_end: str | None = Field(None, description="Global end date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    panels: OverviewPanelsConfig = Field(default_factory=OverviewPanelsConfig, description="Toggle individual report panels.")


class DataOverviewConfig(BaseModel):
    """Top-level configuration for the data-overview launcher."""

    workspace: WorkspaceConfig
    geographic: GeographicConfig
    data: DataManagersConfig = DataManagersConfig()
    overview: OverviewSection = OverviewSection()

    # Keep raw TOML for data-section forwarding.
    _raw_toml: dict[str, Any] = {}

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_toml(
        cls,
        raw_toml: dict[str, Any],
        *,
        base_dir: Path,
    ) -> DataOverviewConfig:
        """Build a validated config from a raw TOML dict.

        Parameters
        ----------
        raw_toml:
            Full parsed TOML payload (already loaded with base-config merging).
        base_dir:
            Directory used to resolve relative paths in workspace/geographic.
        """
        workspace_section = raw_toml.get("workspace", {})
        # Default project_root to TOML directory when absent (stripped by _strip_empty_strings).
        if "project_root" not in workspace_section:
            workspace_section = {**workspace_section, "project_root": base_dir.resolve()}
        else:
            pr = Path(workspace_section["project_root"]).expanduser()
            if not pr.is_absolute():
                pr = (base_dir / pr).resolve()
            workspace_section = {**workspace_section, "project_root": pr}

        data_section = raw_toml.get("data", {})

        geographic_section = raw_toml.get("geographic", {})
        # Resolve dem_init_path relative to TOML location.
        if "dem_init_path" in geographic_section:
            dp = Path(geographic_section["dem_init_path"]).expanduser()
            if not dp.is_absolute():
                dp = (base_dir / dp).resolve()
            geographic_section = {**geographic_section, "dem_init_path": dp}
        elif "dem" in data_section.get("types", []):
            # DEM will be downloaded via API during bootstrap — use a
            # placeholder so GeographicConfig validation passes.
            geographic_section = {
                **geographic_section,
                "dem_init_path": Path("__DEM_API_BOOTSTRAP__"),
            }
        data_cfg = DataManagersConfig.from_toml_section(data_section, base_dir=base_dir)

        overview_section = raw_toml.get("overview", {})

        cfg = cls(
            workspace=WorkspaceConfig(**workspace_section),
            geographic=GeographicConfig(**geographic_section),
            data=data_cfg,
            overview=OverviewSection(**overview_section),
        )
        cfg._raw_toml = dict(raw_toml)
        return cfg
