"""The support fields that cut a domain into zones a parameter can vary on.

A zone field comes from a raster aligned with the domain, from bands along one
axis or from rings around one point. Each one gives the zone of every cell of a
cell mesh, from sample points of the cell.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from hydromodpy.spatial.field.cell_sampling import sampled_zone_fractions
from hydromodpy.spatial.field.field_spatial import Field, WeightedAverageFieldDiscretization
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.raster_support import RasterSupport


def _sampled_on_mesh(
    field: RasterZonesSupportField | GeneratedBandsSupportField | GeneratedRingsSupportField,
    cell_mesh: PlanarCellMesh,
    cell_samples_per_axis: int,
    *,
    total: Literal["samples", "labelled"] = "samples",
) -> WeightedAverageFieldDiscretization:
    """Zone shares of each cell of ``cell_mesh``, read on sample points of the cell."""
    fractions = sampled_zone_fractions(
        cell_mesh, field.zone_id, field.zone_keys, cell_samples_per_axis, total=total
    )
    return WeightedAverageFieldDiscretization(
        mesh=cell_mesh,
        field_id=field.identifier,
        zone_keys=field.zone_keys,
        fractions_by_zone=fractions,
    )


class AliasedSpatialSupportField(Field):
    """Delegate one support field while exposing a different public identifier."""

    def __init__(self, *, identifier: str, delegate: object):
        super().__init__(identifier=identifier)
        self.delegate = delegate
        self.default_cell_samples_per_axis = int(
            getattr(delegate, "default_cell_samples_per_axis", 8)
        )

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return tuple(getattr(self.delegate, "zone_keys", ()))

    def on_mesh(self, cell_mesh: PlanarCellMesh, *, cell_samples_per_axis: int = 10):
        return self.delegate.on_mesh(cell_mesh, cell_samples_per_axis=cell_samples_per_axis)

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)


class RasterZonesSupportField(Field):
    """Generic raster-like zonation support aligned with one domain raster support."""

    def __init__(
        self,
        *,
        identifier: str,
        encoded_codes,
        encoded_to_zone: dict[int, str],
        raster_support: RasterSupport,
        nodata_code: int = 0,
        source_meta: dict[str, str] | None = None,
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        codes = np.asarray(encoded_codes, dtype=np.int32)
        if codes.ndim != 2:
            raise ValueError("encoded_codes must be a 2D integer array")
        if codes.size == 0:
            raise ValueError("encoded_codes cannot be empty")

        mapping = {int(key): str(value).strip() for key, value in dict(encoded_to_zone).items()}
        if not mapping:
            raise ValueError("encoded_to_zone cannot be empty")
        if any(code <= 0 for code in mapping):
            raise ValueError("encoded_to_zone keys must be positive integers")
        if any(label == "" for label in mapping.values()):
            raise ValueError("encoded_to_zone labels cannot be empty")

        if not isinstance(raster_support, RasterSupport):
            raise TypeError("raster_support must be a RasterSupport instance")
        raster_support.assert_complete_domain()
        if raster_support.dx is None or raster_support.dy is None:
            raise ValueError("raster_support must expose dx and dy")

        if raster_support.nrows != codes.shape[0] or raster_support.ncols != codes.shape[1]:
            raise ValueError(
                "raster_support shape mismatch with encoded_codes: "
                f"{(raster_support.nrows, raster_support.ncols)} != {codes.shape}"
            )

        allowed = set(mapping) | {int(nodata_code)}
        present = set(np.unique(codes).astype(int).tolist())
        if not present.issubset(allowed):
            unknown = sorted(present.difference(allowed))
            raise ValueError(f"encoded_codes contains unknown class codes: {unknown}")

        self.encoded_codes = codes
        self.encoded_to_zone = mapping
        self.raster_support = raster_support
        self.nodata_code = int(nodata_code)
        self.source_meta = None if source_meta is None else dict(source_meta)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return tuple(self.encoded_to_zone[key] for key in sorted(self.encoded_to_zone))

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(int(value) for value in self.encoded_codes.shape)

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")

        support = self.raster_support
        xmin = float(support.xmin)
        xmax = float(support.xmax)
        ymin = float(support.ymin)
        ymax = float(support.ymax)
        dx = float(support.dx)
        dy = float(support.dy)
        nrows, ncols = self.shape

        cols = np.floor((x_arr.ravel() - xmin) / dx).astype(int)
        rows = np.floor((ymax - y_arr.ravel()) / dy).astype(int)

        out = np.empty(rows.shape, dtype=object)
        out[:] = ""
        valid = (
            (x_arr.ravel() >= xmin)
            & (x_arr.ravel() < xmax)
            & (y_arr.ravel() >= ymin)
            & (y_arr.ravel() < ymax)
            & (rows >= 0)
            & (rows < nrows)
            & (cols >= 0)
            & (cols < ncols)
        )
        if np.any(valid):
            valid_codes = self.encoded_codes[rows[valid], cols[valid]]
            mapped = np.empty(valid_codes.shape, dtype=object)
            mapped[:] = ""
            for encoded in np.unique(valid_codes):
                if int(encoded) <= 0 or int(encoded) == self.nodata_code:
                    continue
                zone_key = self.encoded_to_zone.get(int(encoded), "")
                if zone_key:
                    mapped[valid_codes == int(encoded)] = zone_key
            out[valid] = mapped
        return out.reshape(x_arr.shape)

    def on_mesh(self, cell_mesh: PlanarCellMesh, *, cell_samples_per_axis: int = 10):
        # A point outside the raster or on nodata counts in no zone.
        return _sampled_on_mesh(self, cell_mesh, cell_samples_per_axis, total="labelled")


class GeneratedBandsSupportField(Field):
    """Analytical band support split along one horizontal axis."""

    def __init__(
        self,
        *,
        identifier: str,
        axis: Literal["x", "y"],
        breaks_abs: list[float],
        labels: list[str],
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        self.axis = str(axis).strip().lower()
        self.breaks_abs = [float(value) for value in breaks_abs]
        self.labels = tuple(str(label).strip() for label in labels)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return self.labels

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        coord = x_arr if self.axis == "x" else y_arr
        bins = np.asarray(self.breaks_abs, dtype=float)
        indexes = np.searchsorted(bins, coord, side="right")
        labels = np.asarray(self.labels, dtype=object)
        return labels[indexes]

    def on_mesh(self, cell_mesh: PlanarCellMesh, *, cell_samples_per_axis: int = 10):
        return _sampled_on_mesh(self, cell_mesh, cell_samples_per_axis)


class GeneratedRingsSupportField(Field):
    """Analytical concentric rings centered on one cartesian point."""

    def __init__(
        self,
        *,
        identifier: str,
        center_x: float,
        center_y: float,
        radii_abs: list[float],
        labels: list[str],
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        self.center_x = float(center_x)
        self.center_y = float(center_y)
        self.radii_abs = [float(value) for value in radii_abs]
        self.labels = tuple(str(label).strip() for label in labels)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

        if any(value <= 0.0 for value in self.radii_abs):
            raise ValueError("radii_abs must contain only strictly positive values")
        if self.radii_abs != sorted(self.radii_abs):
            raise ValueError("radii_abs must be strictly increasing")
        if len(set(self.radii_abs)) != len(self.radii_abs):
            raise ValueError("radii_abs cannot contain duplicates")
        if len(self.labels) != len(self.radii_abs) + 1:
            raise ValueError("labels length must be len(radii_abs) + 1")
        if any(label == "" for label in self.labels):
            raise ValueError("labels cannot contain empty values")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels cannot contain duplicates")

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return self.labels

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        radius = np.sqrt((x_arr - self.center_x) ** 2 + (y_arr - self.center_y) ** 2)
        labels = np.asarray(self.labels, dtype=object)
        indexes = np.searchsorted(np.asarray(self.radii_abs, dtype=float), radius, side="right")
        return labels[indexes]

    def on_mesh(self, cell_mesh: PlanarCellMesh, *, cell_samples_per_axis: int = 10):
        return _sampled_on_mesh(self, cell_mesh, cell_samples_per_axis)
