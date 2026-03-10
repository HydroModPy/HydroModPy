"""Pydantic configuration for water quality data sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WaterQualitySourceConfig(BaseModel):
    """Configuration for ONE water quality data source."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "hubeau"] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Site type (river vs piezometer quality) ---
    site_type: Literal["river", "piezometer"] = Field(
        default="river", description="Type of site: 'river' (qualite_rivieres) or 'piezometer' (qualite_nappes)."
    )

    # --- Parameter filtering ---
    parameters: Optional[list[str]] = Field(
        default=None,
        description="Parameters to keep (e.g. ['pH', 'Nitrates']). None = all parameters.",
    )

    # --- Custom source fields ---
    path: Optional[Path] = Field(
        default=None, description="Directory containing location file and chronicle CSVs."
    )
    col_id: str = Field(default="id", description="Column name for station identifier in location file.")
    col_x: str = Field(default="x", description="Column name for X coordinate in location CSV.")
    col_y: str = Field(default="y", description="Column name for Y coordinate in location CSV.")
    col_crs: str = Field(default="crs", description="Column name for CRS in location CSV.")
    default_crs: str = Field(default="EPSG:4326", description="Default CRS when not in location file.")
    col_datetime: str = Field(default="datetime", description="Column name for datetime in chronicles.")
    col_value: str = Field(default="value", description="Column name for value in chronicles.")

    # --- Spatial mask ---
    mask_path: Optional[Path] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API fallback / nearest ---
    require_observations: bool = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Optional[float] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )
    nearest: bool = Field(
        default=False,
        description="Keep only the nearest station to the extent centroid.",
    )

    # --- Common fields ---
    station_ids: Optional[list[str]] = Field(default=None, description="Explicit station ids.")
    extent: Optional[Literal["watershed", "study_area"]] = Field(default=None)
    force_refresh: bool = Field(default=False, description="Ignore cache and re-download.")

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "WaterQualitySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        return self


class WaterQualityConfig(BaseModel):
    """Top-level water quality configuration (list of sources)."""

    model_config = ConfigDict(extra="forbid")

    sources: list[WaterQualitySourceConfig] = Field(
        ..., min_length=1, description="At least one data source."
    )

    @classmethod
    def from_toml(cls, path: str | Path) -> "WaterQualityConfig":
        """Load config from a TOML file.

        Relative paths (``path``, ``mask_path``) are resolved relative
        to the TOML file's directory.
        """
        path = Path(path).resolve()
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        section = data.get("water_quality", data)
        cfg = cls.model_validate(section)
        _resolve_paths(cfg, path.parent)
        return cfg


def _resolve_paths(cfg: "WaterQualityConfig", toml_dir: Path) -> None:
    """Resolve relative paths in source configs relative to the TOML directory."""
    for src in cfg.sources:
        if src.path is not None and not src.path.is_absolute():
            src.path = (toml_dir / src.path).resolve()
        if src.mask_path is not None and not src.mask_path.is_absolute():
            src.mask_path = (toml_dir / src.mask_path).resolve()
