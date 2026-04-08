"""Pydantic configuration models for the Data Overview launcher.

Loads only ``[workspace]``, ``[geographic]``, ``[data]``, ``[overview]`` from
the TOML — no ``[simulation]``, ``[flow]``, ``[transport]``, ``[solver]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.core.workspace.config import WorkspaceConfig


class OverviewPanelsConfig(BaseModel):
    """Toggle individual report panels on/off."""

    model_config = ConfigDict(extra="forbid")

    map_dem: Annotated[bool, ParamLevel("user")] = Field(True, description="DEM elevation map with stations overlay.")
    map_geology: Annotated[bool, ParamLevel("user")] = Field(True, description="Geology lithology map.")
    map_hydrography: Annotated[bool, ParamLevel("user")] = Field(True, description="River network map with Strahler orders.")
    stats_card: Annotated[bool, ParamLevel("user")] = Field(True, description="Key watershed metrics card.")
    timeseries_discharge: Annotated[bool, ParamLevel("user")] = Field(True, description="Observed discharge time series.")
    timeseries_piezometry: Annotated[bool, ParamLevel("user")] = Field(True, description="Observed piezometric levels time series.")
    climatic_summary: Annotated[bool, ParamLevel("user")] = Field(True, description="Mean monthly precipitation and ETP bars.")
    timeseries_intermittency: Annotated[bool, ParamLevel("user")] = Field(True, description="ONDE flow-state observations timeline.")
    timeseries_water_quality: Annotated[bool, ParamLevel("user")] = Field(True, description="Water quality parameters time series.")
    station_inventory: Annotated[bool, ParamLevel("user")] = Field(True, description="Table listing all stations (type, id, coordinates, period).")


class OverviewSection(BaseModel):
    """Overview report settings (watershed identity card)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, ParamLevel("user")] = Field("", description="Watershed name displayed on report panels. Defaults to workspace catch_name.")
    date_start: Annotated[str | None, ParamLevel("user")] = Field(None, description="Global start date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    date_end: Annotated[str | None, ParamLevel("user")] = Field(None, description="Global end date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    panels: Annotated[OverviewPanelsConfig, ParamLevel("user")] = Field(default_factory=OverviewPanelsConfig, description="Toggle individual report panels.")


class DataOverviewConfig(BaseModel):
    """Top-level configuration for the data-overview launcher."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workspace: Annotated[WorkspaceConfig, ParamLevel("user")] = Field(
        description="Workspace and folder structure configuration.",
    )
    geographic: Annotated[GeographicConfig, ParamLevel("user")] = Field(
        description="Geographic and watershed delineation parameters.",
    )
    data: Annotated[DataManagersConfig, ParamLevel("user")] = Field(
        default_factory=DataManagersConfig,
        description="Data-managers configuration for overview.",
    )
    overview: Annotated[OverviewSection, ParamLevel("user")] = Field(
        default_factory=OverviewSection,
        description="Overview report settings.",
    )

    # Keep raw TOML for data-section forwarding.
    _raw_toml: dict[str, Any] = {}

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
