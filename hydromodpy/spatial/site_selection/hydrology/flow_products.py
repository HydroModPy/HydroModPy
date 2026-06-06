"""Adapter from site-selection config to existing DEM flow products."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.geographic.core.flow_products import (
    FlowProducts,
    build_regional_flow_products,
)
from hydromodpy.spatial.site_selection.config import HydrologyConfig

FlowProductsBuilder = Callable[..., FlowProducts]


@dataclass(frozen=True)
class SiteSelectionFlowProducts:
    """Flow-product bundle plus the parameters used by site selection."""

    products: FlowProducts
    flow_algorithm: str
    dem_correction_type: str
    network_threshold_area_km2: float
    compute_strahler: bool

    def to_manifest_record(self) -> dict[str, Any]:
        """Return a small manifest entry for reproducibility."""

        return {
            "flow_algorithm": self.flow_algorithm,
            "dem_correction_type": self.dem_correction_type,
            "network_threshold_area_km2": self.network_threshold_area_km2,
            "compute_strahler": self.compute_strahler,
            "dem_corrected_path": self.products.correc,
            "flow_direction_path": self.products.direc,
            "flow_accumulation_path": self.products.acc,
        }


def build_site_selection_flow_products(
    *,
    dem_init_path: str | Path,
    output_dir: str | Path,
    hydrology: HydrologyConfig,
    crs_project: str | None = None,
    backend: object | None = None,
    builder: FlowProductsBuilder = build_regional_flow_products,
) -> SiteSelectionFlowProducts:
    """Build DEM flow products by delegating to existing spatial code.

    This function is intentionally thin. It validates the site-selection
    contract and calls ``build_regional_flow_products`` instead of duplicating
    D8, filling/breaching, or accumulation logic.
    """

    if hydrology.flow_algorithm != "d8":
        raise ValueError("site selection currently supports flow_algorithm='d8' only.")

    dem_correction_type = hydrology.dem_correction_type
    products = builder(
        dem_init_path=dem_init_path,
        dem_out_dir_path=output_dir,
        dem_correc_type=dem_correction_type,
        crs_project=crs_project,
        backend=backend,
    )
    return SiteSelectionFlowProducts(
        products=products,
        flow_algorithm=hydrology.flow_algorithm,
        dem_correction_type=dem_correction_type,
        network_threshold_area_km2=hydrology.network_threshold_area_km2,
        compute_strahler=hydrology.compute_strahler,
    )


__all__ = [
    "SiteSelectionFlowProducts",
    "build_site_selection_flow_products",
]
