"""Configuration model for catchment-identification annex workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

DEFAULT_CONFIG_FILE = "run_catchment_identification_config.toml"
DEFAULT_SECTION = "catchment_identification_scan"
LEGACY_SECTION = "watershed_threshold_scan"


def _resolve_optional_path(raw_value: Any, *, base_dir: Path) -> Path | None:
    if raw_value is None:
        return None
    path = Path(str(raw_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


@dataclass(slots=True)
class CatchmentIdentificationConfig:
    """Typed config payload loaded from one TOML section."""

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
    ) -> "CatchmentIdentificationConfig":
        config_path = Path(config_toml).expanduser().resolve()
        with config_path.open("rb") as stream:
            payload = tomllib.load(stream)

        raw_section = payload.get(section)
        if not isinstance(raw_section, dict):
            if section == DEFAULT_SECTION:
                raw_section = payload.get(LEGACY_SECTION)
            elif section == LEGACY_SECTION:
                raw_section = payload.get(DEFAULT_SECTION)
        if not isinstance(raw_section, dict):
            raise KeyError(f"Missing TOML section [{section}] in file: {config_path}")

        base_dir = config_path.parent
        launcher_script = _resolve_optional_path(
            raw_section.get("launcher_script"),
            base_dir=base_dir,
        )
        if launcher_script is not None and not launcher_script.exists():
            raise FileNotFoundError(f"launcher_script not found: {launcher_script}")

        dem_path = _resolve_optional_path(raw_section.get("dem_path"), base_dir=base_dir)
        if dem_path is None:
            raise ValueError(f"[{section}] requires dem_path")
        if not dem_path.exists():
            raise FileNotFoundError(f"DEM file not found: {dem_path}")

        region_polygon_path = _resolve_optional_path(
            raw_section.get("region_polygon_path"),
            base_dir=base_dir,
        )
        if region_polygon_path is not None and not region_polygon_path.exists():
            raise FileNotFoundError(f"region_polygon_path not found: {region_polygon_path}")

        output_dir = _resolve_optional_path(raw_section.get("output_dir"), base_dir=base_dir)
        if output_dir is None:
            output_dir = (base_dir / "outputs").resolve()

        accumulation_area_km2 = float(raw_section.get("accumulation_area_km2", 100.0))
        if accumulation_area_km2 <= 0.0:
            raise ValueError("accumulation_area_km2 must be strictly positive")

        outlet_selection_mode = str(raw_section.get("outlet_selection_mode", "border")).strip().lower()
        if outlet_selection_mode not in {"border", "scan_global"}:
            raise ValueError("outlet_selection_mode must be 'border' or 'scan_global'")

        scan_tile_size_km = float(raw_section.get("scan_tile_size_km", 25.0))
        if scan_tile_size_km <= 0.0:
            raise ValueError("scan_tile_size_km must be > 0")

        scan_max_outlets_per_tile = int(raw_section.get("scan_max_outlets_per_tile", 1))
        if scan_max_outlets_per_tile <= 0:
            raise ValueError("scan_max_outlets_per_tile must be >= 1")

        scan_min_outlet_spacing_km = float(raw_section.get("scan_min_outlet_spacing_km", 8.0))
        if scan_min_outlet_spacing_km < 0.0:
            raise ValueError("scan_min_outlet_spacing_km must be >= 0")

        scan_max_total_outlets = int(raw_section.get("scan_max_total_outlets", 200))
        if scan_max_total_outlets <= 0:
            raise ValueError("scan_max_total_outlets must be >= 1")

        basin_selection_mode = str(raw_section.get("basin_selection_mode", "all_min_area")).strip().lower()
        if basin_selection_mode not in {"all_min_area", "headwater_target"}:
            raise ValueError("basin_selection_mode must be 'all_min_area' or 'headwater_target'")

        headwater_max_strahler_order = int(raw_section.get("headwater_max_strahler_order", 1))
        if headwater_max_strahler_order < 1:
            raise ValueError("headwater_max_strahler_order must be >= 1")

        headwater_min_target_ratio = float(raw_section.get("headwater_min_target_ratio", 0.50))
        if (headwater_min_target_ratio < 0.0) or (headwater_min_target_ratio > 1.0):
            raise ValueError("headwater_min_target_ratio must be in [0, 1]")

        raw_target_basin_area_km2 = raw_section.get("target_basin_area_km2")
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

        target_area_tolerance_ratio = float(raw_section.get("target_area_tolerance_ratio", 0.30))
        if target_area_tolerance_ratio < 0.0:
            raise ValueError("target_area_tolerance_ratio must be >= 0")

        max_basin_overlap_ratio = float(raw_section.get("max_basin_overlap_ratio", 0.05))
        if (max_basin_overlap_ratio < 0.0) or (max_basin_overlap_ratio > 1.0):
            raise ValueError("max_basin_overlap_ratio must be in [0, 1]")

        dem_correction = str(raw_section.get("dem_correction", "breach")).strip().lower()
        if dem_correction not in {"fill", "breach"}:
            raise ValueError("dem_correction must be 'fill' or 'breach'")

        snap_dist = int(raw_section.get("snap_dist", 0))
        if snap_dist < 0:
            raise ValueError("snap_dist must be >= 0")

        gpkg_name = str(raw_section.get("gpkg_name", "watersheds_100km2.gpkg"))
        basins_layer = str(raw_section.get("basins_layer", "bassins_100km2"))
        outlets_layer = str(raw_section.get("outlets_layer", "exutoires_100km2"))
        outlets_csv_name = str(raw_section.get("outlets_csv_name", "exutoires_100km2.csv"))
        save_diagnostic_figures = bool(raw_section.get("save_diagnostic_figures", True))
        figures_dir_name = str(raw_section.get("figures_dir_name", "figures")).strip() or "figures"
        keep_intermediate = bool(raw_section.get("keep_intermediate", True))

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


# Backward-compatible alias.
WatershedThresholdScanConfig = CatchmentIdentificationConfig
