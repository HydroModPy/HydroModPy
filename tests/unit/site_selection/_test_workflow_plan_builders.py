from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts

from ._geojson import write_square_geojson


def make_fake_flow_builder() -> Callable[..., FlowProducts]:
    """Flow products builder that materializes paths under the requested output dir."""

    def fake_flow_builder(**kwargs: Any) -> FlowProducts:
        output_dir = Path(kwargs["dem_out_dir_path"])
        return FlowProducts(
            correc=str(output_dir / "fill.tif"),
            direc=str(output_dir / "direc.tif"),
            acc=str(output_dir / "acc.tif"),
        )

    return fake_flow_builder


def make_fake_delineation_builder(
    calls: dict[str, Any] | None = None,
) -> Callable[..., CatchmentFromPointProducts]:
    """Delineation builder writing a square watershed geojson.

    When ``calls`` is provided, the received kwargs are recorded into it.
    """

    def fake_delineation_builder(**kwargs: Any) -> CatchmentFromPointProducts:
        if calls is not None:
            calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        write_square_geojson(watershed)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    return fake_delineation_builder
