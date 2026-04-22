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

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from rasterio.transform import rowcol

from hydromodpy.spatial.field.core.field_mesh import BaseFieldMesh
from hydromodpy.spatial.field.core.field_spatial import Field
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


@lru_cache(maxsize=None)
def _quadrilateral_sample_weights(n_sub_per_axis: int) -> np.ndarray:
    n = max(2, int(n_sub_per_axis))
    u = (np.arange(n, dtype=float) + 0.5) / float(n)
    v = (np.arange(n, dtype=float) + 0.5) / float(n)
    uu, vv = np.meshgrid(u, v, indexing="xy")
    return np.column_stack(
        (
            ((1.0 - uu) * (1.0 - vv)).ravel(),
            (uu * (1.0 - vv)).ravel(),
            (uu * vv).ravel(),
            ((1.0 - uu) * vv).ravel(),
        )
    )


@lru_cache(maxsize=None)
def _triangle_sample_weights(n_sub_per_axis: int) -> np.ndarray:
    n = max(2, int(n_sub_per_axis))
    u = (np.arange(n, dtype=float) + 0.5) / float(n)
    v = (np.arange(n, dtype=float) + 0.5) / float(n)
    uu, vv = np.meshgrid(u, v, indexing="xy")
    mask = (uu + vv) < 1.0
    uu = uu[mask]
    vv = vv[mask]
    return np.column_stack((1.0 - uu - vv, uu, vv))


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
        zone_codes = np.array(sorted(self.encoded_to_zone), dtype=np.int32)
        self._zone_codes = zone_codes
        self._zone_keys = tuple(self.encoded_to_zone[int(code)] for code in zone_codes)
        max_code = int(zone_codes.max())
        code_to_zone_index = np.full(max_code + 1, -1, dtype=np.int32)
        code_to_zone_index[zone_codes] = np.arange(zone_codes.size, dtype=np.int32)
        self._code_to_zone_index = code_to_zone_index
        known_codes = np.zeros(max_code + 1, dtype=bool)
        known_codes[zone_codes] = True
        self._known_encoded_codes = known_codes

    @property
    def zone_keys(self):
        """Ordered tuple of zone keys used for heterogeneous mapping."""
        return self._zone_keys

    @property
    def shape(self):
        """Raster shape ``(n_rows, n_cols)`` for internal encoded grid."""
        return self.encoded_codes.shape

    @staticmethod
    def _sample_points_in_cell(cell, *, n_sub_per_axis: int):
        """Generate deterministic interior sample points for one mesh cell."""
        verts = np.asarray(cell.vertices, dtype=float)

        if cell.kind == "quadrilateral":
            weights = _quadrilateral_sample_weights(n_sub_per_axis)
            x = np.einsum("pv,v->p", weights, verts[:, 0], optimize=True)
            y = np.einsum("pv,v->p", weights, verts[:, 1], optimize=True)
            return x.ravel(), y.ravel()

        if cell.kind == "triangle":
            weights = _triangle_sample_weights(n_sub_per_axis)
            x = np.einsum("pv,v->p", weights, verts[:, 0], optimize=True)
            y = np.einsum("pv,v->p", weights, verts[:, 1], optimize=True)
            return x, y

        raise ValueError(f"Unsupported cell kind '{cell.kind}'")

    @staticmethod
    def _sample_points_in_cells(
        vertices: np.ndarray, *, cell_kind: str, n_sub_per_axis: int
    ) -> tuple[np.ndarray, np.ndarray]:
        verts = np.asarray(vertices, dtype=float)
        if verts.ndim != 3:
            raise ValueError("vertices must have shape (n_cells, n_vertices, 2)")

        if cell_kind == "quadrilateral":
            weights = _quadrilateral_sample_weights(n_sub_per_axis)
            w0 = weights[:, 0][None, :]
            w1 = weights[:, 1][None, :]
            w2 = weights[:, 2][None, :]
            w3 = weights[:, 3][None, :]
            x = (
                w0 * verts[:, 0, 0:1]
                + w1 * verts[:, 1, 0:1]
                + w2 * verts[:, 2, 0:1]
                + w3 * verts[:, 3, 0:1]
            )
            y = (
                w0 * verts[:, 0, 1:2]
                + w1 * verts[:, 1, 1:2]
                + w2 * verts[:, 2, 1:2]
                + w3 * verts[:, 3, 1:2]
            )
            return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        elif cell_kind == "triangle":
            weights = _triangle_sample_weights(n_sub_per_axis)
            uu = weights[:, 1][None, :]
            vv = weights[:, 2][None, :]
            p0x = verts[:, 0, 0:1]
            p0y = verts[:, 0, 1:2]
            x = p0x + uu * (verts[:, 1, 0:1] - p0x) + vv * (verts[:, 2, 0:1] - p0x)
            y = p0y + uu * (verts[:, 1, 1:2] - p0y) + vv * (verts[:, 2, 1:2] - p0y)
            return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        else:
            raise ValueError(f"Unsupported cell kind '{cell_kind}'")

    def _sample_encoded_codes(self, x, y) -> np.ndarray:
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")

        rows, cols = rowcol(self.transform, x_arr.ravel(), y_arr.ravel(), op=np.floor)
        rows = np.asarray(rows, dtype=int)
        cols = np.asarray(cols, dtype=int)
        out = np.zeros(rows.shape, dtype=np.int32)

        n_rows, n_cols = self.shape
        valid = (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
        if np.any(valid):
            valid_rows = rows[valid]
            valid_cols = cols[valid]
            sampled = np.asarray(self.encoded_codes[valid_rows, valid_cols], dtype=np.int32)
            positive = sampled > 0
            if np.any(positive):
                positive_codes = sampled[positive]
                known = positive_codes < self._known_encoded_codes.size
                if np.any(known):
                    keep = np.zeros(sampled.shape, dtype=bool)
                    positive_positions = np.flatnonzero(positive)
                    keep_positions = positive_positions[known]
                    keep[keep_positions] = self._known_encoded_codes[positive_codes[known]]
                    sampled = np.where(keep, sampled, 0)
                else:
                    sampled = np.zeros_like(sampled, dtype=np.int32)
            out[valid] = sampled

        return out.reshape(x_arr.shape)

    def zone_id(self, x, y):
        """
        Sample geology zone keys at coordinate arrays.

        Coordinates outside raster extent or with encoded class ``0``
        (nodata) are returned as empty key ``""``.
        """
        encoded = self._sample_encoded_codes(x, y)
        out = np.empty(encoded.shape, dtype=object)
        out[:] = ""
        valid_codes = encoded > 0
        if np.any(valid_codes):
            positive_codes = encoded[valid_codes]
            mapped = np.empty(positive_codes.shape, dtype=object)
            mapped[:] = ""
            for code in np.unique(positive_codes):
                mapped[positive_codes == int(code)] = self.encoded_to_zone.get(int(code), "")
            out[valid_codes] = mapped
        return out

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
        n_cells = int(mesh.n_cells)
        fractions_flat = np.zeros((len(zone_keys), n_cells), dtype=float)
        grouped_cells: dict[str, list] = {}
        for cell in mesh.cells:
            grouped_cells.setdefault(cell.kind, []).append(cell)

        for cell_kind, kind_cells in grouped_cells.items():
            if not kind_cells:
                continue

            n_vertices = 4 if cell_kind == "quadrilateral" else 3
            weights = (
                _quadrilateral_sample_weights(n_sub)
                if cell_kind == "quadrilateral"
                else _triangle_sample_weights(n_sub)
            )
            n_points_per_cell = int(weights.shape[0])
            chunk_size = max(1, int(200000 // max(1, n_points_per_cell)))

            for start in range(0, len(kind_cells), chunk_size):
                chunk = kind_cells[start : start + chunk_size]
                cell_indices = np.array([int(cell.index) for cell in chunk], dtype=np.int32)
                if cell_kind == "triangle":
                    for cell in chunk:
                        x_s, y_s = self._sample_points_in_cell(
                            cell,
                            n_sub_per_axis=n_sub,
                        )
                        encoded = self._sample_encoded_codes(x_s, y_s).reshape(-1)
                        valid_codes = encoded[encoded > 0]
                        if valid_codes.size == 0:
                            continue
                        zone_counts = np.bincount(
                            self._code_to_zone_index[valid_codes],
                            minlength=len(zone_keys),
                        )
                        fractions_flat[:, int(cell.index)] = zone_counts / float(valid_codes.size)
                    continue

                vertices = np.empty((len(chunk), n_vertices, 2), dtype=float)
                for idx, cell in enumerate(chunk):
                    vertices[idx, :, :] = np.asarray(cell.vertices, dtype=float)

                x_s, y_s = self._sample_points_in_cells(
                    vertices,
                    cell_kind=cell_kind,
                    n_sub_per_axis=n_sub,
                )
                encoded = self._sample_encoded_codes(x_s, y_s)
                valid = encoded > 0
                if not np.any(valid):
                    continue

                chunk_counts = np.zeros((len(zone_keys), len(chunk)), dtype=np.int32)
                cell_positions = np.repeat(np.arange(len(chunk), dtype=np.int32), n_points_per_cell)
                valid_flat = valid.reshape(-1)
                valid_codes = encoded.reshape(-1)[valid_flat]
                zone_indices = self._code_to_zone_index[valid_codes]
                np.add.at(
                    chunk_counts,
                    (zone_indices, cell_positions[valid_flat]),
                    1,
                )

                valid_counts = np.count_nonzero(valid, axis=1)
                active_cells = valid_counts > 0
                if np.any(active_cells):
                    fractions_flat[:, cell_indices[active_cells]] = (
                        chunk_counts[:, active_cells] / valid_counts[active_cells]
                    )

        fractions_by_zone = {
            key: np.asarray(mesh.to_cell_values(fractions_flat[idx]), dtype=float)
            for idx, key in enumerate(zone_keys)
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
        from hydromodpy.data.variables.geology.config import (
            validate_geology_config_data,
        )
        from hydromodpy.data.variables.geology.io import (
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
        from hydromodpy.data.variables.geology.config import (
            load_geology_toml,
        )

        cfg = load_geology_toml(toml_path, section=section)
        return cls.from_dict(cfg)
