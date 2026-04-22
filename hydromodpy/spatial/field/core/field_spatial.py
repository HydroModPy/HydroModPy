"""
Generic field interface and shared discretization structure.

`Field` is intentionally abstract: it defines the minimal contract expected by
`FieldParam` to project heterogeneous values on a mesh. Concrete geometries
(for example `FieldSquare`) implement the actual spatial logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    from hydromodpy.spatial.field.core.field_mesh import BaseFieldMesh
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from field_mesh import BaseFieldMesh  # type: ignore

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib  # type: ignore[no-redef]


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve a nested TOML section from a dotted path."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


class Field(ABC):
    """
    Abstract field definition.

    Concrete subclasses must implement `on_mesh`, which returns a
    `FieldDiscretization` containing the fractions/weights needed by
    `FieldParam.to_mesh_field(...)`.
    """

    def __init__(self, *, identifier: str):
        ident = str(identifier).strip()
        if ident == "":
            raise ValueError("identifier must be a non-empty string")
        self.identifier = ident

    @abstractmethod
    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        """
        Project this field geometry on a mesh and return a discretization map.
        """

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> Field:
        """Optional constructor hook for subclasses."""
        _ = config
        raise NotImplementedError(f"{cls.__name__}.from_dict is not implemented")

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "field") -> Field:
        """Optional TOML constructor hook for subclasses."""
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        section_cfg = _get_nested_section(payload, section)
        return cls.from_dict(section_cfg)


@dataclass(frozen=True)
class FieldDiscretization(ABC):
    """
    Abstract discretization metadata to project field values onto a mesh.

    Concrete implementations can encode cell-wise contributions in different
    ways, but must expose:
    - an aggregation operator name (`aggregation_name` / `aggregation`),
    - weighted components (`weighted_components`).
    """

    mesh: BaseFieldMesh
    field_id: str

    def __post_init__(self):
        if not isinstance(self.mesh, BaseFieldMesh):
            raise TypeError("mesh must be a BaseFieldMesh instance")
        ident = str(self.field_id).strip()
        if ident == "":
            raise ValueError("field_id must be a non-empty string")
        object.__setattr__(self, "field_id", ident)

    @abstractmethod
    def aggregation_name(self) -> str:
        """Return aggregation operator name (example: 'weighted_average')."""

    @property
    def aggregation(self) -> str:
        """Compatibility accessor for the aggregation operator name."""
        return str(self.aggregation_name()).strip().lower()

    @abstractmethod
    def weighted_components(self) -> tuple[tuple[str, ...], Mapping[str, np.ndarray]]:
        """
        Return weighted components used by `FieldParam.to_mesh_field`.

        Returns
        -------
        tuple
            `(component_keys, weights_by_key)` where each weight array is
            cell-shaped on `mesh`.
        """
