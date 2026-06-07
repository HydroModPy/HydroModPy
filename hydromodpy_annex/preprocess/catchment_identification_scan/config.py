"""Configuration model for catchment-identification annex workflow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.toml_io.loader import load_toml_with_base_config

DEFAULT_CONFIG_FILE = "config_s3_100km2.toml"
DEFAULT_SECTION = "catchment_identification_scan"
DEFAULT_RESULTS_ROOT = str(Path.home() / "HydroModPy")
DEFAULT_RESULTS_SUBDIR = "catchment_identification_scan"


def _resolve_optional_path(raw_value: Any, *, base_dir: Path) -> Path | None:
    if raw_value is None:
        return None
    path = Path(str(raw_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _results_root() -> Path:
    raw_root = os.environ.get("HYDROMODPY_RESULTS_ROOT", DEFAULT_RESULTS_ROOT)
    return Path(raw_root).expanduser().resolve()


def _default_output_name(config_path: Path) -> str:
    stem = config_path.stem.strip()
    if stem.startswith("config_"):
        stem = stem.removeprefix("config_")
    return stem or "default"


def _default_output_dir(config_path: Path) -> Path:
    return (_results_root() / DEFAULT_RESULTS_SUBDIR / _default_output_name(config_path)).resolve()


def _resolve_output_dir(raw_value: Any, *, base_dir: Path, config_path: Path) -> Path:
    if raw_value is None:
        return _default_output_dir(config_path)
    path = Path(str(raw_value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    parts = path.parts
    if parts and parts[0].lower() == "outputs":
        suffix = Path(*parts[1:]) if len(parts) > 1 else Path(_default_output_name(config_path))
        return (_results_root() / DEFAULT_RESULTS_SUBDIR / suffix).resolve()
    return (base_dir / path).resolve()


class _CatchmentIdentificationSection(BaseModel):
    """Raw TOML payload for one catchment-identification run."""

    model_config = ConfigDict(extra="forbid")

    launcher_script: str | Path | None = Field(
        default=None,
        description="Optional launcher script path recorded for run traceability.",
    )
    dem_path: str | Path = Field(description="Projected DEM path.")
    region_polygon_path: str | Path | None = Field(
        default=None,
        description="Optional region polygon path used to clip the DEM.",
    )
    output_dir: str | Path | None = Field(
        default=None,
        description="Output directory path.",
    )
    accumulation_area_km2: float = Field(
        default=100.0,
        description="Minimum contributing area in km2.",
    )
    outlet_selection_mode: str = Field(
        default="border",
        description="Outlet selection mode: 'border' or 'scan_global'.",
    )
    scan_tile_size_km: float = Field(
        default=25.0,
        description="Tile size in km for scan_global outlet search.",
    )
    scan_max_outlets_per_tile: int = Field(
        default=1,
        description="Maximum outlet count retained per scan tile.",
    )
    scan_min_outlet_spacing_km: float = Field(
        default=8.0,
        description="Minimum spacing between retained outlets in km.",
    )
    scan_max_total_outlets: int = Field(
        default=200,
        description="Global outlet count cap for scan_global mode.",
    )
    basin_selection_mode: str = Field(
        default="all_min_area",
        description="Basin selection mode: 'all_min_area' or 'headwater_target'.",
    )
    headwater_max_strahler_order: int = Field(
        default=1,
        description="Maximum Strahler order retained for headwater_target mode.",
    )
    headwater_min_target_ratio: float = Field(
        default=0.50,
        description="Minimum target-area ratio retained for headwater_target mode.",
    )
    target_basin_area_km2: float | None = Field(
        default=None,
        description="Optional target basin area in km2.",
    )
    target_area_tolerance_ratio: float = Field(
        default=0.30,
        description="Relative target-area tolerance.",
    )
    max_basin_overlap_ratio: float = Field(
        default=0.05,
        description="Maximum accepted overlap ratio between retained basins.",
    )
    dem_correction: str = Field(
        default="breach",
        description="DEM correction mode: 'fill' or 'breach'.",
    )
    snap_dist: int = Field(
        default=0,
        description="Outlet snapping distance in m.",
    )
    gpkg_name: str = Field(
        default="watersheds_100km2.gpkg",
        description="Output GeoPackage filename.",
    )
    basins_layer: str = Field(
        default="bassins_100km2",
        description="Output basin layer name.",
    )
    outlets_layer: str = Field(
        default="exutoires_100km2",
        description="Output outlet layer name.",
    )
    outlets_csv_name: str = Field(
        default="exutoires_100km2.csv",
        description="Output outlet CSV filename.",
    )
    save_diagnostic_figures: bool = Field(
        default=True,
        description="Whether diagnostic figures are written.",
    )
    figures_dir_name: str = Field(
        default="figures",
        description="Diagnostic figures subdirectory name.",
    )
    keep_intermediate: bool = Field(
        default=True,
        description="Whether intermediate rasters are kept.",
    )


class CatchmentIdentificationConfig(BaseModel):
    """Typed config payload loaded from one TOML section."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    config_path: Path
    launcher_script: Path | None
    dem_path: Path
    region_polygon_path: Path | None
    output_dir: Path
    accumulation_area_km2: float
    outlet_selection_mode: str
    scan_tile_size_km: float
    scan_max_outlets_per_tile: int
    scan_min_outlet_spacing_km: float
    scan_max_total_outlets: int
    basin_selection_mode: str
    headwater_max_strahler_order: int
    headwater_min_target_ratio: float
    target_basin_area_km2: float | None
    target_area_tolerance_ratio: float
    max_basin_overlap_ratio: float
    dem_correction: str
    snap_dist: int
    gpkg_name: str
    basins_layer: str
    outlets_layer: str
    outlets_csv_name: str
    save_diagnostic_figures: bool
    figures_dir_name: str
    keep_intermediate: bool

    @classmethod
    def from_toml(
        cls,
        config_toml: str | Path,
        *,
        section: str = DEFAULT_SECTION,
    ) -> CatchmentIdentificationConfig:
        config_path = Path(config_toml).expanduser().resolve()
        payload = load_toml_with_base_config(config_path)

        raw_section = payload.get(section)
        if not isinstance(raw_section, dict):
            raise KeyError(f"Missing TOML section [{section}] in file: {config_path}")

        section_data = _CatchmentIdentificationSection.model_validate(raw_section)
        base_dir = config_path.parent
        launcher_script = _resolve_optional_path(
            section_data.launcher_script,
            base_dir=base_dir,
        )
        if launcher_script is not None and not launcher_script.exists():
            raise FileNotFoundError(f"launcher_script not found: {launcher_script}")

        dem_path = _resolve_optional_path(section_data.dem_path, base_dir=base_dir)
        if dem_path is None:
            raise ValueError(f"[{section}] requires dem_path")
        if not dem_path.exists():
            raise FileNotFoundError(f"DEM file not found: {dem_path}")

        region_polygon_path = _resolve_optional_path(
            section_data.region_polygon_path,
            base_dir=base_dir,
        )
        if region_polygon_path is not None and not region_polygon_path.exists():
            raise FileNotFoundError(f"region_polygon_path not found: {region_polygon_path}")

        output_dir = _resolve_output_dir(
            section_data.output_dir,
            base_dir=base_dir,
            config_path=config_path,
        )

        accumulation_area_km2 = float(section_data.accumulation_area_km2)
        if accumulation_area_km2 <= 0.0:
            raise ValueError("accumulation_area_km2 must be strictly positive")

        outlet_selection_mode = str(section_data.outlet_selection_mode).strip().lower()
        if outlet_selection_mode not in {"border", "scan_global"}:
            raise ValueError("outlet_selection_mode must be 'border' or 'scan_global'")

        scan_tile_size_km = float(section_data.scan_tile_size_km)
        if scan_tile_size_km <= 0.0:
            raise ValueError("scan_tile_size_km must be > 0")

        scan_max_outlets_per_tile = int(section_data.scan_max_outlets_per_tile)
        if scan_max_outlets_per_tile <= 0:
            raise ValueError("scan_max_outlets_per_tile must be >= 1")

        scan_min_outlet_spacing_km = float(section_data.scan_min_outlet_spacing_km)
        if scan_min_outlet_spacing_km < 0.0:
            raise ValueError("scan_min_outlet_spacing_km must be >= 0")

        scan_max_total_outlets = int(section_data.scan_max_total_outlets)
        if scan_max_total_outlets <= 0:
            raise ValueError("scan_max_total_outlets must be >= 1")

        basin_selection_mode = str(section_data.basin_selection_mode).strip().lower()
        if basin_selection_mode not in {"all_min_area", "headwater_target"}:
            raise ValueError("basin_selection_mode must be 'all_min_area' or 'headwater_target'")

        headwater_max_strahler_order = int(section_data.headwater_max_strahler_order)
        if headwater_max_strahler_order < 1:
            raise ValueError("headwater_max_strahler_order must be >= 1")

        headwater_min_target_ratio = float(section_data.headwater_min_target_ratio)
        if (headwater_min_target_ratio < 0.0) or (headwater_min_target_ratio > 1.0):
            raise ValueError("headwater_min_target_ratio must be in [0, 1]")

        raw_target_basin_area_km2 = section_data.target_basin_area_km2
        target_basin_area_km2: float | None
        if raw_target_basin_area_km2 is None:
            target_basin_area_km2 = None
        else:
            target_basin_area_km2 = float(raw_target_basin_area_km2)
            if target_basin_area_km2 <= 0.0:
                raise ValueError("target_basin_area_km2 must be strictly positive when provided")
            if target_basin_area_km2 < accumulation_area_km2:
                raise ValueError(
                    "target_basin_area_km2 must be >= accumulation_area_km2 "
                    f"({accumulation_area_km2:.3f})"
                )

        target_area_tolerance_ratio = float(section_data.target_area_tolerance_ratio)
        if target_area_tolerance_ratio < 0.0:
            raise ValueError("target_area_tolerance_ratio must be >= 0")

        max_basin_overlap_ratio = float(section_data.max_basin_overlap_ratio)
        if (max_basin_overlap_ratio < 0.0) or (max_basin_overlap_ratio > 1.0):
            raise ValueError("max_basin_overlap_ratio must be in [0, 1]")

        dem_correction = str(section_data.dem_correction).strip().lower()
        if dem_correction not in {"fill", "breach"}:
            raise ValueError("dem_correction must be 'fill' or 'breach'")

        snap_dist = int(section_data.snap_dist)
        if snap_dist < 0:
            raise ValueError("snap_dist must be >= 0")

        gpkg_name = str(section_data.gpkg_name)
        basins_layer = str(section_data.basins_layer)
        outlets_layer = str(section_data.outlets_layer)
        outlets_csv_name = str(section_data.outlets_csv_name)
        save_diagnostic_figures = bool(section_data.save_diagnostic_figures)
        figures_dir_name = str(section_data.figures_dir_name).strip() or "figures"
        keep_intermediate = bool(section_data.keep_intermediate)

        return cls(
            config_path=config_path,
            launcher_script=launcher_script,
            dem_path=dem_path,
            region_polygon_path=region_polygon_path,
            output_dir=output_dir,
            accumulation_area_km2=accumulation_area_km2,
            outlet_selection_mode=outlet_selection_mode,
            scan_tile_size_km=scan_tile_size_km,
            scan_max_outlets_per_tile=scan_max_outlets_per_tile,
            scan_min_outlet_spacing_km=scan_min_outlet_spacing_km,
            scan_max_total_outlets=scan_max_total_outlets,
            basin_selection_mode=basin_selection_mode,
            headwater_max_strahler_order=headwater_max_strahler_order,
            headwater_min_target_ratio=headwater_min_target_ratio,
            target_basin_area_km2=target_basin_area_km2,
            target_area_tolerance_ratio=target_area_tolerance_ratio,
            max_basin_overlap_ratio=max_basin_overlap_ratio,
            dem_correction=dem_correction,
            snap_dist=snap_dist,
            gpkg_name=gpkg_name,
            basins_layer=basins_layer,
            outlets_layer=outlets_layer,
            outlets_csv_name=outlets_csv_name,
            save_diagnostic_figures=save_diagnostic_figures,
            figures_dir_name=figures_dir_name,
            keep_intermediate=keep_intermediate,
        )
