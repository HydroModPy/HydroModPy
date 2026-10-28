"""The document that describes a built domain, written for the mesh generator.

It holds what the request resolved to, the rasters written for it and their
extent over the active cells, in place of a live ``Domain`` object.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.spatial.domain.capability import (
    ACTIVE_CELLS_PATH,
    BOTTOM_PATH,
    DOMAIN_BUILD,
    DOMAIN_SCHEMA,
    THICKNESS_PATH,
    DomainBuildRequest,
)


@dataclass(frozen=True, slots=True)
class ResolvedDomainRequest:
    """What the request resolved to, before anything is written."""

    inputs: DomainBuildRequest
    dem_path: Path
    dem_digest: str
    dem_bytes: int
    mask_path: Path | None
    mask_digest: str | None
    mask_bytes: int | None
    mask_layer: str | None
    substratum_path: Path | None
    substratum_digest: str | None
    substratum_bytes: int | None
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]

    @property
    def mask_target(self) -> tuple[Path, str] | None:
        """The mask file and the layer it resolved to, or nothing.

        The pair, never the two apart: a path without a resolved layer is a
        state the worker cannot produce, and what reads it should not have
        to admit one.
        """
        if self.mask_path is None or self.mask_layer is None:
            return None
        return (self.mask_path, self.mask_layer)


def _statistics(values: np.ndarray, active: np.ndarray) -> dict[str, float | None]:
    """Return the extent of *values* over the active cells, or nulls."""
    selected = np.asarray(values, dtype=float)[active]
    selected = selected[np.isfinite(selected)]
    if selected.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.min(selected)),
        "max": float(np.max(selected)),
        "mean": float(np.mean(selected)),
    }


def build_domain_document(
    resolved: ResolvedDomainRequest,
    *,
    crs: Any,
    transform: Any,
    bounds: Any,
    nodata: float | None,
    top: np.ndarray,
    bottom: np.ndarray,
    thickness: np.ndarray,
    active: np.ndarray,
) -> dict[str, Any]:
    """Return the document a mesh generator is handed instead of a live object.

    Every statistic is taken over the **active** cells and says so. A mean over
    the whole grid would average the nodata sentinel into an elevation, which
    is what makes this document worth writing rather than deriving.
    """
    decl = DOMAIN_BUILD
    nrows, ncols = (int(top.shape[0]), int(top.shape[1]))
    cell_area = abs(float(transform.a) * float(transform.e))
    active_count = int(np.count_nonzero(active))
    return {
        "schema": DOMAIN_SCHEMA,
        "process": {"id": decl.id, "version": decl.version},
        "crs": crs.to_string(),
        "grid": {
            "nrows": nrows,
            "ncols": ncols,
            "dx": abs(float(transform.a)),
            "dy": abs(float(transform.e)),
            "bounds": {
                "xmin": float(bounds.left),
                "ymin": float(bounds.bottom),
                "xmax": float(bounds.right),
                "ymax": float(bounds.top),
            },
            "transform": [float(value) for value in tuple(transform)[:6]],
            "nodata": None if nodata is None else float(nodata),
        },
        "depth_model": resolved.inputs.depth_model.model_dump(mode="json"),
        "layers": [
            {
                "index": 0,
                # The top is an input and not an artefact of this job: naming
                # the resource of ``inputset.json`` is what lets a reader find
                # the digest of the raster the bottom was derived from.
                "top": {"input": "dem", "sha256": resolved.dem_digest},
                "bottom": BOTTOM_PATH,
                # The raster a ``raster`` depth model read, by input and digest
                # like the top; null for a depth model that reads none.
                "substratum": (
                    None
                    if resolved.substratum_digest is None
                    else {"input": "substratum", "sha256": resolved.substratum_digest}
                ),
                "thickness": THICKNESS_PATH,
            }
        ],
        "active_cells": {
            "path": ACTIVE_CELLS_PATH,
            "count": active_count,
            "total": nrows * ncols,
            "area_m2": active_count * cell_area,
            # The input and its digest, never its href: the mask lives outside
            # the job by construction, and a document that named the path it
            # sat at on the machine that built it would describe that machine.
            "mask": (
                None
                if resolved.mask_digest is None
                else {"input": "mask", "sha256": resolved.mask_digest}
            ),
        },
        "statistics": {
            "over": "active_cells",
            "top": _statistics(top, active),
            "bottom": _statistics(bottom, active),
            "thickness": _statistics(thickness, active),
        },
    }
