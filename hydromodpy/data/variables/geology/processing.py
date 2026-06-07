"""
Geology raster post-processing helpers.

These helpers are intentionally pure and side-effect free so they are easy to
unit-test and reuse from ``GeologyField``.

Design intent
-------------
The core ``FieldParam`` workflow expects:
- stable string zone keys (for parameter dictionaries),
- positive encoded classes on raster cells,
- optional post-processing hooks (land/sea overrides).

This module performs exactly those transformations.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def normalize_zone_key(raw: Any) -> str:
    """
    Normalize one raw geology code into a stable string key.

    Examples
    --------
    normalize_zone_key(12)      -> "12"
    normalize_zone_key(12.0)    -> "12"
    normalize_zone_key(12.5)    -> "12.5"
    normalize_zone_key("A31")   -> "A31"
    """
    if isinstance(raw, (int, np.integer)):
        return str(int(raw))
    if isinstance(raw, (float, np.floating)):
        value = float(raw)
        if np.isfinite(value) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(raw).strip()


def encode_numeric_raster(raw_codes, *, nodata_value=None):
    """
    Encode a numeric raster to positive integer classes.

    Returns
    -------
    tuple
        ``(encoded_codes, encoded_to_zone)`` where:
        - ``encoded_codes`` is ``np.int32`` with ``0`` as nodata,
        - ``encoded_to_zone`` maps positive encoded values to string keys.
    """
    raw = np.asarray(raw_codes)
    if raw.ndim != 2:
        raise ValueError("raw_codes must be a 2D array")

    raw_f = raw.astype(float)
    valid = np.isfinite(raw_f)
    if nodata_value is not None and np.isfinite(float(nodata_value)):
        valid &= raw_f != float(nodata_value)

    encoded = np.zeros(raw_f.shape, dtype=np.int32)
    encoded_to_zone: dict[int, str] = {}
    if not np.any(valid):
        return encoded, encoded_to_zone

    unique_raw = np.unique(raw_f[valid])
    for idx, raw_value in enumerate(unique_raw, start=1):
        mask = valid & (raw_f == raw_value)
        encoded[mask] = int(idx)
        encoded_to_zone[int(idx)] = normalize_zone_key(raw_value)
    return encoded, encoded_to_zone


def apply_landsea_override(
    encoded_codes,
    *,
    encoded_to_zone: dict[int, str],
    landsea_array,
    sea_value: float = 0.0,
    override_zone_key: str = "1",
):
    """
    Override geology classes where land/sea mask equals ``sea_value``.

    This function mutates a copy and returns updated values.
    """
    codes = np.asarray(encoded_codes, dtype=np.int32).copy()
    lsm = np.asarray(landsea_array, dtype=float)
    if lsm.shape != codes.shape:
        raise ValueError("landsea_array must match encoded_codes shape")

    sea_mask = np.isfinite(lsm) & np.isclose(lsm, float(sea_value))
    if not np.any(sea_mask):
        return codes, dict(encoded_to_zone)

    out_map = dict(encoded_to_zone)
    normalized_override = normalize_zone_key(override_zone_key)
    existing = [k for k, v in out_map.items() if v == normalized_override]
    if existing:
        encoded_override = int(existing[0])
    else:
        encoded_override = int(max(out_map.keys(), default=0) + 1)
        out_map[encoded_override] = normalized_override

    codes[sea_mask] = encoded_override
    return codes, out_map


def uniformize_sea_zone_on_dataframe(
    gdf,
    *,
    enabled: bool = True,
    zone_key_column: str = "zone_key",
    sea_field: str,
    sea_value: str,
    sea_zone_key: str = "SEA",
):
    """
    Optionally assign one uniform zone key to sea polygons in a GeoDataFrame.

    Parameters
    ----------
    sea_field : attribute column that distinguishes land from sea polygons
    sea_value : value in ``sea_field`` that marks sea polygons
    """
    if not bool(enabled):
        return gdf, {
            "applied": False,
            "reason": "disabled",
            "count": 0,
            "sea_field": str(sea_field),
            "sea_value": str(sea_value),
            "sea_zone_key": str(sea_zone_key),
        }

    zone_key_col = str(zone_key_column).strip()
    if zone_key_col == "" or zone_key_col not in gdf.columns:
        return gdf, {
            "applied": False,
            "reason": f"missing_zone_key_column:{zone_key_col}",
            "count": 0,
            "sea_field": str(sea_field),
            "sea_value": str(sea_value),
            "sea_zone_key": str(sea_zone_key),
        }

    sea_field_key = str(sea_field).strip()
    if sea_field_key == "" or sea_field_key not in gdf.columns:
        return gdf, {
            "applied": False,
            "reason": f"missing_field:{sea_field_key}",
            "count": 0,
            "sea_field": sea_field_key,
            "sea_value": str(sea_value),
            "sea_zone_key": str(sea_zone_key),
        }

    sea_mask = (
        gdf[sea_field_key].astype(str).str.strip().str.upper() == str(sea_value).strip().upper()
    )
    n_sea = int(np.count_nonzero(sea_mask.to_numpy()))
    if n_sea <= 0:
        return gdf, {
            "applied": False,
            "reason": "no_matching_sea_polygon",
            "count": 0,
            "sea_field": sea_field_key,
            "sea_value": str(sea_value),
            "sea_zone_key": str(sea_zone_key),
        }

    out = gdf.copy()
    out.loc[sea_mask, zone_key_col] = normalize_zone_key(sea_zone_key)
    return out, {
        "applied": True,
        "reason": "ok",
        "count": n_sea,
        "sea_field": sea_field_key,
        "sea_value": str(sea_value),
        "sea_zone_key": normalize_zone_key(sea_zone_key),
    }


def build_zone_class_index_on_dataframe(
    gdf,
    *,
    zone_key_column: str = "zone_key",
    class_index_column: str = "class_idx",
    min_unique: int = 2,
):
    """
    Build a stable class index column from zone keys for plotting/analysis.
    """
    zone_key_col = str(zone_key_column).strip()
    if zone_key_col == "":
        raise ValueError("zone_key_column cannot be empty")
    if zone_key_col not in gdf.columns:
        raise KeyError(f"Missing zone key column '{zone_key_col}'")

    zone_keys = gdf[zone_key_col].astype(str).str.strip()
    out = gdf.loc[zone_keys != ""].copy()
    if out.empty:
        raise ValueError("No non-empty zone key found in dataframe")

    zone_keys = out[zone_key_col].astype(str).str.strip()
    _, class_idx = np.unique(zone_keys.to_numpy(), return_inverse=True)
    out[str(class_index_column).strip() or "class_idx"] = class_idx.astype(float)

    counts = zone_keys.value_counts()
    if int(counts.size) < int(max(1, min_unique)):
        raise ValueError(
            "Only one geology class found in the global map. "
            "Check source path, code_field, clip polygon, or source coverage."
        )
    return out, counts
