"""
Concrete field geometry on the unit square split into two zones.

`FieldSquare` keeps the previous square-specific behavior while `Field`
remains generic/abstract. The geometry is defined by one separating line and
one side assignment (`zone1_side`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from hydromodpy.spatial.field.core.field_spatial import Field, _get_nested_section
from hydromodpy.spatial.field.core.field_mesh import BaseFieldMesh
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib  # type: ignore[no-redef]


SUPPORTED_LINES = (
    "diag_main",
    "diag_anti",
    "axis_vertical",
    "axis_horizontal",
)
SUPPORTED_SIDES = ("positive", "negative")


def _normalize_line_name(value: str) -> str:
    key = str(value).strip().lower()
    if key not in SUPPORTED_LINES:
        allowed = ", ".join(SUPPORTED_LINES)
        raise ValueError(f"Unsupported line '{value}'. Allowed: {allowed}")
    return key


class FieldSquare(Field):
    """
    Split the unit square into two named zones separated by one line.
    """

    def __init__(
        self,
        *,
        line: str = "diag_main",
        zone1_side: str = "positive",
        identifier: str = "field_square",
        zone1_name: str = "granite",
        zone2_name: str = "micaschists",
    ):
        super().__init__(identifier=identifier)

        line_key = _normalize_line_name(line)
        side_key = str(zone1_side).strip().lower()
        if side_key not in SUPPORTED_SIDES:
            allowed = ", ".join(SUPPORTED_SIDES)
            raise ValueError(
                f"Unsupported zone1_side '{zone1_side}'. Allowed: {allowed}"
            )
        z1 = str(zone1_name).strip()
        z2 = str(zone2_name).strip()
        if z1 == "" or z2 == "":
            raise ValueError("zone1_name and zone2_name must be non-empty strings")

        self.line = line_key
        self.zone1_side = side_key
        self.zone1_name = z1
        self.zone2_name = z2

    @staticmethod
    def _evaluate_line_function(*, x: np.ndarray, y: np.ndarray, line: str):
        if line == "diag_main":
            return y - x
        if line == "diag_anti":
            return y + x - 1.0
        if line == "axis_vertical":
            return x - 0.5
        if line == "axis_horizontal":
            return y - 0.5
        raise ValueError(f"Unsupported line '{line}'")

    @staticmethod
    def _build_zone_map(
        *,
        signed_distance: np.ndarray,
        zone1_side: str,
        zone1_name: str,
        zone2_name: str,
    ):
        out = np.empty(signed_distance.shape, dtype=object)
        positive = signed_distance >= 0.0
        negative = ~positive

        if zone1_side == "positive":
            out[positive] = zone1_name
            out[negative] = zone2_name
        else:
            out[positive] = zone2_name
            out[negative] = zone1_name
        return out

    def signed_side(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")
        return self._evaluate_line_function(x=x_arr, y=y_arr, line=self.line)

    def zone_id(self, x, y):
        side = self.signed_side(x, y)
        return self._build_zone_map(
            signed_distance=side,
            zone1_side=self.zone1_side,
            zone1_name=self.zone1_name,
            zone2_name=self.zone2_name,
        )

    @staticmethod
    def _sample_points_in_cell(cell, *, n_sub_per_axis: int):
        """Generate deterministic interior sample points for one cell."""
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
            x = (
                w0 * verts[0, 0]
                + w1 * verts[1, 0]
                + w2 * verts[2, 0]
                + w3 * verts[3, 0]
            )
            y = (
                w0 * verts[0, 1]
                + w1 * verts[1, 1]
                + w2 * verts[2, 1]
                + w3 * verts[3, 1]
            )
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

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        """
        Build field-to-mesh discretization using intra-cell sampling fractions.
        """
        frac_zone1 = np.empty(mesh.n_cells, dtype=float)
        frac_zone2 = np.empty(mesh.n_cells, dtype=float)

        for cell in mesh.cells:
            x_s, y_s = self._sample_points_in_cell(
                cell, n_sub_per_axis=cell_samples_per_axis
            )
            zones = self.zone_id(x_s, y_s)

            c1 = int(np.count_nonzero(zones == self.zone1_name))
            c2 = int(np.count_nonzero(zones == self.zone2_name))
            total = max(c1 + c2, 1)

            frac_zone1[cell.index] = float(c1) / float(total)
            frac_zone2[cell.index] = float(c2) / float(total)

        fractions_by_zone = {
            self.zone1_name: np.asarray(mesh.to_cell_values(frac_zone1), dtype=float),
            self.zone2_name: np.asarray(mesh.to_cell_values(frac_zone2), dtype=float),
        }
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=(self.zone1_name, self.zone2_name),
            fractions_by_zone=fractions_by_zone,
        )

    def _encode_zones(self, zones):
        raw = np.asarray(zones, dtype=object)
        encoded = np.empty(raw.shape, dtype=float)
        encoded[raw == self.zone1_name] = 1.0
        encoded[raw == self.zone2_name] = 2.0
        return encoded

    def zone_display(self, *, n_plot: int = 320):
        """Build a smooth 2D zone map on the continuous unit-square domain."""
        n = max(40, int(n_plot))
        xy = np.linspace(0.0, 1.0, n, dtype=float)
        x, y = np.meshgrid(xy, xy, indexing="xy")
        zones = self.zone_id(x, y)
        return self._encode_zones(zones)

    def as_dict(self):
        return {
            "id": str(self.identifier),
            "line": str(self.line),
            "zone1_side": str(self.zone1_side),
            "zone1_name": str(self.zone1_name),
            "zone2_name": str(self.zone2_name),
        }

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> "FieldSquare":
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping")

        line = config.get("line")
        if line is None:
            family = str(config.get("line_family", "")).strip().lower()
            orientation = str(config.get("line_orientation", "")).strip().lower()
            if family == "diagonal":
                if orientation not in {"main", "anti"}:
                    raise ValueError(
                        "For line_family='diagonal', line_orientation must be 'main' or 'anti'"
                    )
                line = f"diag_{orientation}"
            elif family in {"symmetry_axis", "axis"}:
                if orientation not in {"vertical", "horizontal"}:
                    raise ValueError(
                        "For line_family='symmetry_axis', line_orientation must be "
                        "'vertical' or 'horizontal'"
                    )
                line = f"axis_{orientation}"
            else:
                raise KeyError(
                    "Field config must provide either 'line' or "
                    "('line_family', 'line_orientation')"
                )

        return cls(
            line=str(line),
            zone1_side=str(config.get("zone1_side", "positive")),
            identifier=str(config.get("id", config.get("identifier", "field_square"))),
            zone1_name=str(config.get("zone1_name", "granite")),
            zone2_name=str(config.get("zone2_name", "micaschists")),
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "field") -> "FieldSquare":
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        section_cfg = _get_nested_section(payload, section)
        return cls.from_dict(section_cfg)
