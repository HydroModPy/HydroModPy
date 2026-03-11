"""
Geology spatial field for heterogeneous parameter mapping on simulation meshes.

Purpose
-------
This module defines `GeologyField`, a concrete implementation of the generic
`Field` interface based on geology classes (typically read from raster data).
Its role is to convert raw geology support into reusable *spatial fractions*
on a target mesh.

Pipeline in the field framework
-------------------------------
1) Build `GeologyField` from config/data (`from_toml` or `from_dict`).
2) Call `on_mesh(mesh)` to obtain per-cell fractions of geology zones.
3) Pass the returned discretization to
   `FieldParam(kind="heterogeneous", values_by_key=...)`.
4) `FieldParam.to_mesh_field(...)` computes one numerical value per mesh cell
   using weighted aggregation.

Design choice
-------------
The geometry and the physical values are intentionally separated:
- `GeologyField` handles *where* zones are located.
- `FieldParam` handles *which value* each zone receives.

This allows:
- reusing the same geology support for multiple calibrated variables
  (for example K, Sy, porosity),
- changing parameter values without recomputing geometry logic.

What this module does not do
----------------------------
- It does not run calibration.
- It does not store calibrated values.
- It does not directly produce model outputs.

It only provides the spatial support layer required before value mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
from rasterio.transform import rowcol

from hydromodpy.data_managers.geology.geology_config import (
    load_geology_toml,
    validate_geology_config_data,
)
from hydromodpy.data_managers.geology.geology_io import load_geology_encoded_grid
from hydromodpy.data_managers.geology.geology_io import (
    load_geology_encoded_grid_on_raster_support,
)
from hydromodpy.field.core.field_mesh import BaseFieldMesh
from hydromodpy.field.core.field_spatial import Field
from hydromodpy.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


class GeologyField(Field):
    """
    Geology-driven implementation of the generic spatial `Field` interface.

    This class stores a geology map (encoded raster classes) and exposes one
    key operation: `on_mesh(mesh)`. The operation does not assign parameter
    values directly; instead, it computes *zone fractions per mesh cell*.
    Those fractions are then combined with physical values by `FieldParam`.

    Why this split is important
    ---------------------------
    - `GeologyField` answers: "which geology zones are present in each cell?"
    - `FieldParam(kind="heterogeneous", values_by_key=...)` answers:
      "which numerical value is associated to each zone key?"
    - `FieldParam.to_mesh_field(discretization)` performs the weighted
      aggregation and returns one numerical value per mesh cell.

    In practice, this keeps geometry independent from parameter calibration.
    You can change values (`granite`, `micaschists`, ...) without rebuilding
    geometry, and you can reuse the same field structure for several parameters
    (e.g., hydraulic conductivity, storativity, porosity).

    Parameters
    ----------
    identifier : str
        Spatial field identifier. It must match
        `FieldParam.field_spatial_id` when using heterogeneous parameters, so
        that the correct spatial support is used at mapping time.
    encoded_codes : array-like
        2D integer grid of encoded geology classes.
        Convention: `0` means nodata / undefined zone.
    encoded_to_zone : mapping[int, str]
        Dictionary converting encoded class numbers to zone keys expected in
        `FieldParam.values_by_key` (example: `{1: "granite", 2: "micaschists"}`).
    transform :
        Raster affine transform used to convert world coordinates `(x, y)` into
        raster indices `(row, col)`.
    crs :
        Optional CRS metadata for traceability. It is stored but not required
        by `on_mesh`.
    source_kind : str, default="raster"
        Informative source label (`"raster"` or `"vector"`).
    default_cell_samples_per_axis : int, default=8
        Default sub-sampling density used by `on_mesh` to estimate zone
        fractions inside each mesh cell. Higher values improve interface
        accuracy but increase runtime.

    Notes
    -----
    - Coordinates outside raster coverage, or raster code `0`, are treated as
      empty zone (`""`) and ignored in fraction counts.
    - For mixed cells crossing geology boundaries, fractions are estimated by
      deterministic point sampling inside each cell.
    - Output of `on_mesh` is a `WeightedAverageFieldDiscretization` object.

    Examples
    --------
    Build from TOML and discretize on a mesh:

    >>> field = GeologyField.from_toml(
    ...     "hydromodpy/data_managers/geology/cases/run_geology_case.toml",
    ...     section="geology",
    ... )
    >>> discretization = field.on_mesh(mesh, cell_samples_per_axis=10)

    Then map zone values to cell values:

    >>> # values_by_key is defined in FieldParam:
    >>> # {"granite": 10.0, "micaschists": 3.5}
    >>> # cell_values = field_param.to_mesh_field(discretization)
    >>> # one scalar value per mesh cell is returned
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
        """Raster shape `(n_rows, n_cols)` for internal encoded grid."""
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

        Notes
        -----
        - Coordinates outside raster extent are returned as empty key `""`.
        - Encoded class `0` (nodata) is also returned as empty key `""`.
        """
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")

        # Convert world coordinates (x, y) to raster indices (row, col).
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
            # Translate encoded class numbers to zone keys expected by FieldParam.
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

        Parameters
        ----------
        mesh : BaseFieldMesh
            Target mesh where geology information must be discretized. The mesh
            provides:
            - `mesh.cells`: iterable of cells with geometry and `cell.index`,
            - `mesh.n_cells`: number of cells,
            - `mesh.to_cell_values(...)`: helper to reshape/normalize vectors
              into the mesh cell-value layout.
        cell_samples_per_axis : int, optional
            Number of interior samples per local axis for each cell.
            Minimum enforced value is `2`.
            Higher values better resolve sharp geology interfaces but increase
            computation time.

        Returns
        -------
        WeightedAverageFieldDiscretization
            Discretization object containing:
            - `field_id`: this field identifier,
            - `zone_keys`: ordered geology keys,
            - `fractions_by_zone`: one float array per key with fraction values
              in `[0, 1]` for every mesh cell.

        Notes
        -----
        Per cell, the method:
        1) samples interior points,
        2) maps each sampled point to one geology key via `zone_id`,
        3) computes relative frequencies (fractions) for all zone keys.

        Cells with no valid sampled points (outside raster or nodata only)
        keep zero fractions for all zones.
        """
        # Enforce at least 2 to keep a meaningful 2D sampling pattern.
        n_sub = max(2, int(cell_samples_per_axis))

        # Keep a stable and explicit ordering of zone keys
        # (important for deterministic downstream mapping).
        zone_keys = self.zone_keys

        # Allocate one flat fraction vector per zone key.
        # Each vector has one slot per mesh cell (indexed by cell.index).
        fractions_flat = {
            key: np.zeros(int(mesh.n_cells), dtype=float)
            for key in zone_keys
        }

        # Iterate over all mesh cells and estimate zone proportions cell-by-cell.
        for cell in mesh.cells:
            # 1) Deterministically sample interior points of the current cell.
            x_s, y_s = self._sample_points_in_cell(cell, n_sub_per_axis=n_sub)

            # 2) Convert sampled coordinates to geology keys.
            #    reshape(-1) ensures a 1D vector for counting operations.
            zones = np.asarray(self.zone_id(x_s, y_s), dtype=object).reshape(-1)

            # Keep only valid keys:
            # - empty strings correspond to nodata/outside-raster samples.
            valid = np.array([str(z).strip() != "" for z in zones], dtype=bool)
            n_valid = int(np.count_nonzero(valid))

            # If no valid sample exists in this cell, keep all fractions to zero
            # and continue with next cell.
            if n_valid == 0:
                continue

            # Restrict counts to valid sampled keys only.
            zones_valid = zones[valid]

            # 3) For each known zone key, compute:
            #    fraction = (# samples of that key) / (# valid samples).
            for key in zone_keys:
                count = int(np.count_nonzero(zones_valid == key))
                fractions_flat[key][cell.index] = float(count) / float(n_valid)

        # Convert flat vectors into the mesh cell-value container expected by
        # downstream code (shape/layout delegated to mesh implementation).
        fractions_by_zone = {
            key: np.asarray(mesh.to_cell_values(values), dtype=float)
            for key, values in fractions_flat.items()
        }

        # Return a generic weighted discretization object.
        # `FieldParam` will consume this object to map zone fractions
        # to actual physical values per mesh cell.
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=zone_keys,
            fractions_by_zone=fractions_by_zone,
        )

    def as_dict(self):
        """
        Return a compact metadata snapshot of this geology field.

        The output is intentionally lightweight and JSON-friendly:
        it includes only simple metadata needed for inspection, logging,
        and quick summaries. Heavy internal data (for example the full
        encoded raster array or affine transform details) is not exported.

        Returns
        -------
        dict[str, object]
            Mapping with the following keys:
            - `id`: field identifier used to link with `FieldParam.field_spatial_id`.
            - `source_kind`: source label (typically `"raster"` or `"vector"`).
            - `shape`: encoded raster shape as `(n_rows, n_cols)`.
            - `zone_keys`: ordered geology keys expected in heterogeneous mapping.
            - `default_cell_samples_per_axis`: default sub-sampling density used
              by `on_mesh` when no explicit value is provided.

        Notes
        -----
        This dictionary is a metadata view, not a full persistence format.
        It is sufficient for diagnostics, but not enough to reconstruct a full
        `GeologyField` instance on its own.
        """
        return {
            "id": str(self.identifier),
            "source_kind": str(self.source_kind),
            "shape": tuple(int(v) for v in self.shape),
            "zone_keys": tuple(self.zone_keys),
            "default_cell_samples_per_axis": int(self.default_cell_samples_per_axis),
        }

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> "GeologyField":
        """
        Build field from validated geology config mapping.

        Example
        -------
        field = GeologyField.from_dict(
            {
                "id": "field_geology",
                "source": {"path": "data/Brittany/dem/regional dem.tif", "kind": "raster"},
            }
        )
        """
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
        """
        Build field directly from one TOML section.

        Example
        -------
        field = GeologyField.from_toml(
            "hydromodpy/data_managers/geology/cases/run_geology_case.toml",
            section="geology",
        )
        """
        cfg = load_geology_toml(toml_path, section=section)
        return cls.from_dict(cfg)

    @classmethod
    def from_watershed_config(
        cls,
        geology_config,
        *,
        raster_support,
    ) -> "GeologyField":
        """
        Build one geology field from the legacy watershed `GeologyConfig`
        together with an explicit `RasterSupport`.

        This constructor is meant for `Domain`: geology is configured only by
        its own config block, while the target spatial reduction/rasterization
        window is defined by the domain topographic support.
        """
        from hydromodpy.watershed_legacy.geology_config import GeologyConfig

        if geology_config is None:
            geology_cfg = GeologyConfig()
        elif isinstance(geology_config, GeologyConfig):
            geology_cfg = geology_config
        elif isinstance(geology_config, Mapping):
            geology_cfg = GeologyConfig.model_validate(dict(geology_config))
        else:
            raise TypeError(
                "geology_config must be a GeologyConfig instance, mapping, or None"
            )

        if bool(geology_cfg.landsea):
            raise ValueError(
                "Domain GeologyField pipeline does not support legacy landsea=True flag. "
                "Please use landsea=None/false."
            )
        if raster_support is None:
            raise ValueError("raster_support is required to build geology on domain support")

        source_rel = Path(str(geology_cfg.types_obs))
        source_path = (
            source_rel
            if source_rel.is_absolute()
            else (Path(geology_cfg.geo_path) / source_rel)
        )

        cfg = validate_geology_config_data(
            {
                "id": str(geology_cfg.id),
                "source": {
                    "path": str(source_path),
                    "kind": "auto",
                    "code_field": str(geology_cfg.fields_obs),
                    "all_touched": False,
                },
                "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
            }
        )
        loaded = load_geology_encoded_grid_on_raster_support(
            cfg,
            raster_support=raster_support,
        )
        return cls(
            identifier=str(cfg["id"]),
            encoded_codes=loaded["encoded_codes"],
            encoded_to_zone=loaded["encoded_to_zone"],
            transform=loaded["transform"],
            crs=loaded["crs"],
            source_kind=str(loaded["source_kind"]),
            default_cell_samples_per_axis=int(cfg.get("cell_samples_per_axis", 8)),
        )


