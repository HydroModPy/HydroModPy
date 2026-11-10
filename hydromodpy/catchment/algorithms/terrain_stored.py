"""Write and read one terrain product as its rasters and ``terrain.json``.

The product store keeps one directory per key, and this codec drops the
rasters of a :class:`~hydromodpy.catchment.algorithms.flow_products.FlowProducts`
into it: the conditioned DEM, the D8 directions and the accumulation, or only
the last two for a DEM the user conditioned, whose file stays the source. Each
raster is stored tiled, deflate-compressed and lossless, in the dtype, nodata,
CRS and geotransform the engine wrote. A read restores each one uncompressed
under the same facts, so no engine ever reads the stored encoding.
``terrain.json`` keeps the format version, the method, the conventions, the
file names and their byte counts, the undrained cell counts and the
capped-breach report, which the rasters alone cannot say.
"""

from __future__ import annotations

import json
from pathlib import Path

import rasterio

from hydromodpy.catchment.algorithms.flow_products import (
    ACCUMULATION_TRANSFORM,
    ACCUMULATION_UNITS,
    FlowProducts,
    TerrainRequest,
    conditioning_method,
)
from hydromodpy.catchment.terrain.artifacts import raster_crs, raster_nodata
from hydromodpy.catchment.terrain.port import (
    CappedBreach,
    CappedBreachReport,
    ConditionedDem,
    ConditioningExtent,
    DrainageDirections,
    FlowAccumulation,
)
from hydromodpy.catchment.terrain.undrained import UndrainedCells

SCHEMA_VERSION = "hydromodpy.terrain_product.v1"
"""Version of this stored format, written in the product key and in ``terrain.json``."""

_JSON = "terrain.json"

_POINTER_CONVENTION = "d8_wbt"

_BLOCK = 512
"""Tile side of a stored raster."""


def write_terrain(products: FlowProducts, directory: Path) -> None:
    """Write ``products`` into ``directory`` as its rasters and ``terrain.json``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    conditioned = products.accumulation.directions.conditioned_dem
    provided = conditioned.method == "provided"
    sources = {"direc": Path(products.direc), "acc": Path(products.acc)}
    if not provided:
        sources["correc"] = Path(products.correc)
    files: dict[str, dict[str, object]] = {}
    for role, source in sources.items():
        _store_raster(source, directory / source.name)
        files[role] = {"name": source.name, "bytes": (directory / source.name).stat().st_size}
    undrained = products.undrained
    report = conditioned.breach_report
    document: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "method": _method_document(conditioned.method),
        "conditioned_name": None if provided else Path(products.correc).name,
        "pointer_convention": _POINTER_CONVENTION,
        "accumulation": {"units": ACCUMULATION_UNITS, "transform": ACCUMULATION_TRANSFORM},
        "nodata": products.accumulation.nodata,
        "crs": conditioned.crs,
        "breach_report": None if report is None else report.to_document(),
        "undrained": None
        if undrained is None
        else {"without_descent": undrained.without_descent, "strict_pits": undrained.strict_pits},
        "files": files,
    }
    (directory / _JSON).write_text(json.dumps(document), encoding="utf-8")


def read_terrain(directory: Path, request: TerrainRequest) -> FlowProducts:
    """Restore the stored stack into ``request.out_dir`` and describe it.

    A document of another format version, a missing key or a stored file whose
    size differs from the one recorded raises ``ValueError``, so the store
    discards the product and the run builds it again. Each stored raster is
    restored uncompressed under its recorded name. A DEM the user conditioned
    is described on the file of this run, never copied.
    """
    directory = Path(directory)
    try:
        meta = json.loads((directory / _JSON).read_text(encoding="utf-8"))
        if meta["schema"] != SCHEMA_VERSION:
            raise ValueError(f"format {meta['schema']!r}, this build reads {SCHEMA_VERSION!r}")
        files = meta["files"]
        for entry in files.values():
            stored = directory / entry["name"]
            if stored.stat().st_size != entry["bytes"]:
                raise ValueError(f"{entry['name']} does not hold the recorded byte count")
        undrained = None if meta["undrained"] is None else UndrainedCells(**meta["undrained"])
        report_doc = meta["breach_report"]
        breach_report = None if report_doc is None else CappedBreachReport.from_document(report_doc)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"The stored terrain product in {directory} is unreadable: {exc!r}. Delete it."
        ) from exc
    request.out_dir.mkdir(parents=True, exist_ok=True)
    restored = {role: request.out_dir / entry["name"] for role, entry in files.items()}
    for role, target in restored.items():
        _restore_raster(directory / files[role]["name"], target)

    if request.method == "provided":
        conditioned = ConditionedDem.provided(request.dem)
    else:
        correc = restored["correc"]
        conditioned = ConditionedDem(
            path=correc,
            method=conditioning_method(request.method, request.capped_breach),
            extent=ConditioningExtent.regional(),
            crs=raster_crs(correc),
            breach_report=breach_report,
        )
    directions = DrainageDirections(
        path=restored["direc"],
        pointer_convention=_POINTER_CONVENTION,
        conditioned_dem=conditioned,
    )
    accumulation = FlowAccumulation(
        path=restored["acc"],
        units=ACCUMULATION_UNITS,
        transform=ACCUMULATION_TRANSFORM,
        directions=directions,
        nodata=raster_nodata(restored["acc"]),
    )
    return FlowProducts(accumulation=accumulation, undrained=undrained)


def _method_document(method: object) -> object:
    """Return the conditioning method as JSON, the limits for a capped breach."""
    if isinstance(method, CappedBreach):
        return {"max_depth_m": method.max_depth_m, "max_distance_m": method.max_distance_m}
    return method


def _store_raster(src: Path, dst: Path) -> None:
    """Copy the raster at *src* to *dst*, tiled and deflate-compressed without loss."""
    with rasterio.open(str(src)) as opened:
        profile = opened.profile.copy()
        profile.update(
            tiled=True,
            blockxsize=_BLOCK,
            blockysize=_BLOCK,
            compress="deflate",
            predictor=1,
            num_threads="ALL_CPUS",
        )
        with rasterio.open(str(dst), "w", **profile) as target:
            for index in range(1, opened.count + 1):
                target.write(opened.read(index), index)


def _restore_raster(src: Path, dst: Path) -> None:
    """Copy the stored raster at *src* to *dst* uncompressed, with the same facts."""
    with rasterio.open(str(src)) as opened:
        profile = opened.profile.copy()
        for option in ("compress", "predictor", "tiled", "blockxsize", "blockysize"):
            profile.pop(option, None)
        with rasterio.open(str(dst), "w", **profile) as target:
            for index in range(1, opened.count + 1):
                target.write(opened.read(index), index)


__all__ = ["SCHEMA_VERSION", "read_terrain", "write_terrain"]
