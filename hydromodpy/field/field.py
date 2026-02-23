"""
Field geometry definition for splitting the unit square into two zones.

`Field` is independent from `FieldParam` and from mesh generation.
It defines a geometry identifier (example: "field_square") and can be
applied on any mesh through `on_mesh(mesh)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from hydromodpy.field.field_mesh import BaseFieldMesh

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


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _normalize_line_name(value: str) -> str:
    key = str(value).strip().lower()
    if key not in SUPPORTED_LINES:
        allowed = ", ".join(SUPPORTED_LINES)
        raise ValueError(f"Unsupported line '{value}'. Allowed: {allowed}")
    return key


class Field:
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
        line_key = _normalize_line_name(line)
        side_key = str(zone1_side).strip().lower()
        if side_key not in SUPPORTED_SIDES:
            allowed = ", ".join(SUPPORTED_SIDES)
            raise ValueError(f"Unsupported zone1_side '{zone1_side}'. Allowed: {allowed}")
        ident = str(identifier).strip()
        if ident == "":
            raise ValueError("identifier must be a non-empty string")
        z1 = str(zone1_name).strip()
        z2 = str(zone2_name).strip()
        if z1 == "" or z2 == "":
            raise ValueError("zone1_name and zone2_name must be non-empty strings")

        self.line = line_key
        self.zone1_side = side_key
        self.identifier = ident
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
        """
        Generate deterministic interior sample points for one cell.
        """
        n = max(2, int(n_sub_per_axis))
        verts = np.asarray(cell.vertices, dtype=float)

        if cell.kind == "quadrilateral":
            u = (np.arange(n, dtype=float) + 0.5) / float(n)
            v = (np.arange(n, dtype=float) + 0.5) / float(n)
            uu, vv = np.meshgrid(u, v, indexing="xy")
            # Bilinear mapping from unit square to quadrilateral corners:
            # v0=(0,0), v1=(1,0), v2=(1,1), v3=(0,1)
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

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        """
        Build field-to-mesh discretization.

        For the current two-zone split, each cell receives percentages:
        - estimated by deterministic intra-cell sampling,
        - so cells crossed by the interface line can receive mixed fractions.

        The returned structure also specifies the aggregation operator that
        should be applied by `FieldParam` (`weighted_average`).
        """
        frac_zone1 = np.empty(mesh.n_cells, dtype=float)
        frac_zone2 = np.empty(mesh.n_cells, dtype=float)

        for cell in mesh.cells:
            x_s, y_s = self._sample_points_in_cell(cell, n_sub_per_axis=cell_samples_per_axis)
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

        return FieldDiscretization(
            mesh=mesh,
            zone_keys=(self.zone1_name, self.zone2_name),
            fractions_by_zone=fractions_by_zone,
            aggregation="weighted_average",
            field_id=self.identifier,
        )

    def _encode_zones(self, zones):
        raw = np.asarray(zones, dtype=object)
        encoded = np.empty(raw.shape, dtype=float)
        encoded[raw == self.zone1_name] = 1.0
        encoded[raw == self.zone2_name] = 2.0
        return encoded

    def zone_display(self, *, n_plot: int = 320):
        """
        Build a smooth 2D zone map on the continuous unit-square domain.
        """
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
    def from_dict(cls, config: Mapping[str, Any]) -> "Field":
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
    def from_toml(
        cls,
        toml_path: str | Path,
        section: str = "field",
    ) -> "Field":
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        section_cfg = _get_nested_section(payload, section)
        return cls.from_dict(section_cfg)


@dataclass(frozen=True)
class FieldDiscretization:
    """
    Discretization metadata to project field values onto a mesh.

    Attributes
    ----------
    mesh : BaseFieldMesh
        Target mesh.
    zone_keys : tuple[str, ...]
        Ordered keys expected in `FieldParam.values_by_key`.
    fractions_by_zone : dict[str, np.ndarray]
        Per-zone fractions on cells (same mesh cell shape for each key).
    aggregation : str
        Aggregation operator name. Current value: "weighted_average".
    field_id : str
        Identifier of the source field definition.
    """

    mesh: BaseFieldMesh
    zone_keys: tuple[str, ...]
    fractions_by_zone: dict[str, np.ndarray]
    aggregation: str
    field_id: str
