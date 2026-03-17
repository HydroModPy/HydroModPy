"""
Geology spatial field for heterogeneous parameter mapping on simulation meshes.

Purpose
-------
This module defines ``GeologyField``, a concrete implementation of the generic
``Field`` interface based on geology classes (typically read from raster data).
Its role is to convert raw geology support into reusable *spatial fractions*
on a target mesh.

Pipeline in the field framework
-------------------------------
1) Build ``GeologyField`` from encoded grid data.
2) Call ``on_mesh(mesh)`` to obtain per-cell fractions of geology zones.
3) Pass the returned discretization to
   ``FieldParam(kind="heterogeneous", values_by_key=...)``.
4) ``FieldParam.to_mesh_field(...)`` computes one numerical value per mesh cell
   using weighted aggregation.

Design choice
-------------
The geometry and the physical values are intentionally separated:
- ``GeologyField`` handles *where* zones are located.
- ``FieldParam`` handles *which value* each zone receives.

This allows:
- reusing the same geology support for multiple calibrated variables
  (for example K, Sy, porosity),
- changing parameter values without recomputing geometry logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
from rasterio.transform import rowcol

from hydromodpy.field.core.field_mesh import BaseFieldMesh
from hydromodpy.field.core.field_spatial import Field
from hydromodpy.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


class GeologyField(Field):
    """
    Geology-driven implementation of the generic spatial ``Field`` interface.

    This class stores a geology map (encoded raster classes) and exposes one
    key operation: ``on_mesh(mesh)``. The operation does not assign parameter
    values directly; instead, it computes *zone fractions per mesh cell*.
    Those fractions are then combined with physical values by ``FieldParam``.

    Parameters
    ----------
    identifier : str
        Spatial field identifier. Must match ``FieldParam.field_spatial_id``
        for heterogeneous parameter mapping.
    encoded_codes : array-like
        2D integer grid of encoded geology classes.
        Convention: ``0`` means nodata / undefined zone.
    encoded_to_zone : mapping[int, str]
        Dictionary converting encoded class numbers to zone keys
        (example: ``{1: "granite", 2: "micaschists"}``).
    transform :
        Raster affine transform for ``(x, y) → (row, col)`` conversion.
    crs :
        Optional CRS metadata for traceability.
    source_kind : str, default="raster"
        Informative source label (``"raster"`` or ``"vector"``).
    default_cell_samples_per_axis : int, default=8
        Default sub-sampling density used by ``on_mesh``.
    """

    def __init__(
        self,
        *,
        identifier: str,
        encoded_codes,
        encoded_to_zone: Mapping[int, str],
        transform,
        crs=None,
        source_kind: str = "raster",
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        codes = np.asarray(encoded_codes, dtype=np.int32)
        if codes.ndim != 2:
            raise ValueError("encoded_codes must be a 2D integer array")
        if codes.size == 0:
            raise ValueError("encoded_codes cannot be empty")

        mapping = {int(k): str(v) for k, v in dict(encoded_to_zone).items()}
        if len(mapping) == 0:
            raise ValueError("encoded_to_zone cannot be empty")
        if any(int(k) <= 0 for k in mapping):
            raise ValueError("encoded_to_zone keys must be positive integers")
        if any(str(v).strip() == "" for v in mapping.values()):
            raise ValueError("encoded_to_zone values cannot be empty")

        self.encoded_codes = codes
        self.encoded_to_zone = mapping
        self.transform = transform
        self.crs = crs
        self.source_kind = str(source_kind).strip().lower()
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

    @property
    def zone_keys(self):
        """Ordered tuple of zone keys used for heterogeneous mapping."""
        return tuple(self.encoded_to_zone[k] for k in sorted(self.encoded_to_zone))

    @property
    def shape(self):
        """Raster shape ``(n_rows, n_cols)`` for internal encoded grid."""
        return self.encoded_codes.shape

    @staticmethod
    def _sample_points_in_cell(cell, *, n_sub_per_axis: int):
        """Generate deterministic interior sample points for one mesh cell."""
        n = max(2, int(n_sub_per_axis))
        verts = np.asarray(cell.vertices, dtype=float)

        if cell.kind == "quadrilateral":
            u = (np.arange(n, dtype=float) + 0.5) / float(n)
            v = (np.arange(n, dtype=float) + 0.5) / float(n)
            uu, vv = np.meshgrid(u, v, indexing="xy")
            w0 = (1.0 - uu) * (1.0 - vv)
            w1 = uu * (1.0 - vv)
            w2 = uu * vv
            w3 = (1.0 - uu) * vv
            x = w0 * verts[0, 0] + w1 * verts[1, 0] + w2 * verts[2, 0] + w3 * verts[3, 0]
            y = w0 * verts[0, 1] + w1 * verts[1, 1] + w2 * verts[2, 1] + w3 * verts[3, 1]
            return x.ravel(), y.ravel()

        if cell.kind == "triangle":
            u = (np.arange(n, dtype=float) + 0.5) / float(n)
            v = (np.arange(n, dtype=float) + 0.5) / float(n)
            uu, vv = np.meshgrid(u, v, indexing="xy")
            mask = (uu + vv) < 1.0
            uu = uu[mask]
            vv = vv[mask]
            p0, p1, p2 = verts[0], verts[1], verts[2]
            x = p0[0] + uu * (p1[0] - p0[0]) + vv * (p2[0] - p0[0])
            y = p0[1] + uu * (p1[1] - p0[1]) + vv * (p2[1] - p0[1])
            return x, y

        raise ValueError(f"Unsupported cell kind '{cell.kind}'")

    def zone_id(self, x, y):
        """
        Sample geology zone keys at coordinate arrays.

        Coordinates outside raster extent or with encoded class ``0``
        (nodata) are returned as empty key ``""``.
        """
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")

        rows, cols = rowcol(self.transform, x_arr.ravel(), y_arr.ravel(), op=np.floor)
        rows = np.asarray(rows, dtype=int)
        cols = np.asarray(cols, dtype=int)

        out = np.empty(rows.shape, dtype=object)
        out[:] = ""
        n_rows, n_cols = self.shape
        valid = (
            (rows >= 0)
            & (rows < n_rows)
            & (cols >= 0)
            & (cols < n_cols)
        )

        if np.any(valid):
            valid_rows = rows[valid]
            valid_cols = cols[valid]
            valid_codes = self.encoded_codes[valid_rows, valid_cols]
            mapped = np.empty(valid_codes.shape, dtype=object)
            mapped[:] = ""
            for encoded in np.unique(valid_codes):
                if int(encoded) <= 0:
                    continue
                zone_key = self.encoded_to_zone.get(int(encoded), "")
                if zone_key:
                    mapped[valid_codes == int(encoded)] = zone_key
            out[valid] = mapped

        return out.reshape(x_arr.shape)

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        """
        Project geology zones onto a target mesh as per-cell zone fractions.

        Works with both regular (structured) and irregular (triangular,
        unstructured) meshes — any mesh implementing ``BaseFieldMesh``.

        Parameters
        ----------
        mesh : BaseFieldMesh
            Target mesh providing ``cells``, ``n_cells``, ``to_cell_values``.
        cell_samples_per_axis : int, optional
            Sub-sampling density per local axis for each cell (minimum 2).

        Returns
        -------
        WeightedAverageFieldDiscretization
        """
        n_sub = max(2, int(cell_samples_per_axis))
        zone_keys = self.zone_keys

        fractions_flat = {
            key: np.zeros(int(mesh.n_cells), dtype=float)
            for key in zone_keys
        }

        for cell in mesh.cells:
            x_s, y_s = self._sample_points_in_cell(cell, n_sub_per_axis=n_sub)
            zones = np.asarray(self.zone_id(x_s, y_s), dtype=object).reshape(-1)

            valid = np.array([str(z).strip() != "" for z in zones], dtype=bool)
            n_valid = int(np.count_nonzero(valid))
            if n_valid == 0:
                continue

            zones_valid = zones[valid]
            for key in zone_keys:
                count = int(np.count_nonzero(zones_valid == key))
                fractions_flat[key][cell.index] = float(count) / float(n_valid)

        fractions_by_zone = {
            key: np.asarray(mesh.to_cell_values(values), dtype=float)
            for key, values in fractions_flat.items()
        }

        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=zone_keys,
            fractions_by_zone=fractions_by_zone,
        )

    def as_dict(self):
        """Return a compact metadata snapshot of this geology field."""
        return {
            "id": str(self.identifier),
            "source_kind": str(self.source_kind),
            "shape": tuple(int(v) for v in self.shape),
            "zone_keys": tuple(self.zone_keys),
            "default_cell_samples_per_axis": int(self.default_cell_samples_per_axis),
        }

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> "GeologyField":
        """Build field from validated geology config mapping (standalone use)."""
        from hydromodpy.data_managers.variables.geology.config_cases import (
            validate_geology_config_data,
        )
        from hydromodpy.data_managers.variables.geology.io import (
            load_geology_encoded_grid,
        )

        cfg = validate_geology_config_data(config)
        loaded = load_geology_encoded_grid(cfg)
        return cls(
            identifier=str(cfg["id"]),
            encoded_codes=loaded["encoded_codes"],
            encoded_to_zone=loaded["encoded_to_zone"],
            transform=loaded["transform"],
            crs=loaded["crs"],
            source_kind=str(loaded["source_kind"]),
            default_cell_samples_per_axis=int(cfg.get("cell_samples_per_axis", 8)),
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "geology") -> "GeologyField":
        """Build field directly from one TOML section (standalone use)."""
        from hydromodpy.data_managers.variables.geology.config_cases import (
            load_geology_toml,
        )

        cfg = load_geology_toml(toml_path, section=section)
        return cls.from_dict(cfg)
