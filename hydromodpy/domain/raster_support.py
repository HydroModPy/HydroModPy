from __future__ import annotations
"""
Raster support metadata used to place 2D surfaces in space.

This module separates spatial referencing from raster values:
- `Surface` stores the 2D numerical values,
- `RasterSupport` stores where those values live in space.

Keeping both concerns separate makes surface operations simpler and avoids
passing larger objects such as `Geographic` into low-level domain classes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isclose
from typing import Any


@dataclass(frozen=True)
class RasterSupport:
    """
    Minimal spatial support for one raster-like 2D array.

    This object stores the spatial metadata independently from the raster
    values themselves. It is intentionally limited to the metadata already
    available in HydroModPy's current geographic workflow.

    Attributes
    ----------
    crs : str | None
        Coordinate reference system identifier (for example ``"EPSG:2154"``).
    dx, dy : float | None
        Cell size along the x and y directions. Keeping two distinct values
        avoids assuming square cells.
    xmin, xmax, ymin, ymax : float | None
        Spatial extent of the raster support.
    nrows, ncols : int | None
        Raster shape, when known.
    nodata : float | None
        Sentinel value used to mark invalid or absent cells in the raster.
    """

    crs: str | None = None
    dx: float | None = None
    dy: float | None = None
    xmin: float | None = None
    xmax: float | None = None
    ymin: float | None = None
    ymax: float | None = None
    nrows: int | None = None
    ncols: int | None = None
    nodata: float | None = None

    @classmethod
    def from_georeferencing(
        cls,
        georeferencing: Mapping[str, object] | None,
        *,
        shape: tuple[int, int] | None = None,
        nodata: float | None = None,
    ) -> "RasterSupport":
        """
        Build one raster support from an explicit georeferencing mapping.

        Expected input
        --------------
        The expected keys match the historical `Domain.georeferencing` payload:
        `crs`, `dx`, `dy`, `xmin`, `xmax`, `ymin`, `ymax`.

        Optional extra metadata can be injected through:
        - `shape`, to populate `nrows` and `ncols`,
        - `nodata`, to store the raster nodata sentinel.

        This method is intentionally narrow: it consumes only explicit spatial
        metadata and does not depend on a larger object such as `Geographic`.
        """
        georef = dict(georeferencing or {})

        kwargs: dict[str, Any] = {
            "crs": georef.get("crs"),
            "dx": georef.get("dx"),
            "dy": georef.get("dy"),
            "xmin": georef.get("xmin"),
            "xmax": georef.get("xmax"),
            "ymin": georef.get("ymin"),
            "ymax": georef.get("ymax"),
            "nodata": nodata,
        }
        if shape is not None:
            kwargs["nrows"] = int(shape[0])
            kwargs["ncols"] = int(shape[1])
        return cls(**kwargs)

    def as_georeferencing_dict(self) -> dict[str, object]:
        """
        Return the historical `Domain.georeferencing` view of this support.

        Only the keys already used by `Domain` are exported here:
        `crs`, `dx`, `dy`, `xmin`, `xmax`, `ymin`, `ymax`.

        This gives a stable bridge between the newer `RasterSupport` object and
        the pre-existing dictionary-based API.
        """
        out: dict[str, object] = {}
        for key in ("crs", "dx", "dy", "xmin", "xmax", "ymin", "ymax"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    def assert_complete_domain(self) -> None:
        """
        Validate that this support has all metadata required to compare domains.

        A complete domain definition requires:
        - CRS,
        - extent (xmin, xmax, ymin, ymax),
        - raster shape (nrows, ncols).
        """
        missing: list[str] = []
        for key in ("crs", "xmin", "xmax", "ymin", "ymax", "nrows", "ncols"):
            if getattr(self, key) is None:
                missing.append(key)
        if missing:
            raise ValueError(
                "RasterSupport is missing required domain metadata: "
                + ", ".join(missing)
            )

    def assert_same_geographic_domain(
        self,
        other: "RasterSupport",
        *,
        atol: float = 1.0e-9,
    ) -> None:
        """
        Ensure two raster supports represent exactly the same geographic domain.

        This comparison checks:
        - CRS equality (string-normalized),
        - extent equality (`xmin`, `xmax`, `ymin`, `ymax`) within `atol`.
        """
        if not isinstance(other, RasterSupport):
            raise TypeError(f"Expected RasterSupport, got {type(other)!r}.")

        self.assert_complete_domain()
        other.assert_complete_domain()

        crs_a = str(self.crs).strip().lower()
        crs_b = str(other.crs).strip().lower()
        if crs_a != crs_b:
            raise ValueError(f"CRS mismatch: {self.crs!r} != {other.crs!r}.")

        numeric_keys = ("xmin", "xmax", "ymin", "ymax")
        for key in numeric_keys:
            a = float(getattr(self, key))
            b = float(getattr(other, key))
            if not isclose(a, b, rel_tol=0.0, abs_tol=float(atol)):
                raise ValueError(
                    f"Domain extent mismatch for '{key}': {a} != {b} "
                    f"(abs_tol={atol})."
                )
