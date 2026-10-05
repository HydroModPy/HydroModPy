"""Custom crossings loader: a vector file the user drew or collected.

The file is read once into the fixed records of the variable. A file without a
``kind`` column, or with a value outside the allowed ones, is refused by name:
a crossing of unknown kind cannot be told from one the notch must leave alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.config import KINDS

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

logger = get_logger(__name__)

VECTOR_EXTENSIONS = ("*.gpkg", "*.shp", "*.geojson")


def vector_file(path: str | Path) -> Path:
    """The vector file a custom source names: the file itself, or the first one of a folder."""
    from hydromodpy.data.common.io_helpers import is_scaffold_example

    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"Custom crossings path not found: {candidate}")
    if candidate.is_dir():
        for pattern in VECTOR_EXTENSIONS:
            for found in sorted(candidate.glob(pattern)):
                if not is_scaffold_example(found):
                    return found
        raise ValueError(f"Custom crossings folder {candidate} holds no vector file.")
    if candidate.suffix.lower() not in {ext.removeprefix("*") for ext in VECTOR_EXTENSIONS}:
        raise ValueError(
            f"Custom crossings file {candidate} is not a vector file "
            f"(expected one of {', '.join(VECTOR_EXTENSIONS)})."
        )
    return candidate


def load_custom(source_cfg: Any, *, path: Path | None = None) -> gpd.GeoDataFrame:
    """The records of a custom file, in the CRS the file declares (or ``default_crs``).

    *path* is the vector file when the caller already found it, for instance
    relative to the TOML directory; otherwise ``source_cfg.path`` names it.
    """
    import geopandas as gpd

    path = vector_file(source_cfg.path if path is None else path)
    frame = gpd.read_file(path)
    if "kind" not in frame.columns:
        raise ValueError(
            f"Custom crossings file {path} has no 'kind' column; it must hold one of "
            f"{list(KINDS)} for each feature."
        )
    kind = frame["kind"].astype(str).str.strip().str.lower().tolist()
    unknown = sorted({value for value in kind if value not in KINDS})
    if unknown:
        raise ValueError(
            f"Custom crossings file {path}: 'kind' value(s) {unknown} are not allowed, "
            f"use {list(KINDS)}."
        )
    if frame.crs is None:
        crs = str(source_cfg.default_crs)
        logger.warning("Custom crossings file %s carries no CRS; using default_crs=%s.", path, crs)
        frame = frame.set_crs(crs)
    keep = ~(frame.geometry.isna() | frame.geometry.is_empty)
    frame = frame[keep.to_numpy()]
    kind = [value for value, kept in zip(kind, keep.to_numpy(), strict=True) if kept]
    return records.build(
        frame.geometry.tolist(),
        kind=kind,
        source="custom",
        name=_text(frame, "name"),
        drop_m=_numbers(frame, "drop_m"),
        crs=str(frame.crs),
    )


def _text(frame: gpd.GeoDataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return [""] * len(frame)
    return ["" if value is None or value != value else str(value) for value in frame[column]]


def _numbers(frame: gpd.GeoDataFrame, column: str) -> list[float]:
    if column not in frame.columns:
        return [float("nan")] * len(frame)
    import pandas as pd

    return pd.to_numeric(frame[column], errors="coerce").astype(float).tolist()
