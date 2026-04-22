"""Calibrable parameters: annotations, space, transforms, discovery.

A Pydantic field becomes calibrable by attaching a ``Calibrable`` instance via
``Field.json_schema_extra['calibrable']`` — or by being referenced in a TOML
``[calibration.parameters]`` block. Discovery walks a config tree and emits
``CalibParameter`` entries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Calibrable:
    """Metadata attached to a Pydantic field to mark it calibrable.

    Usage::

        k_aquifer: float = Field(
            default=1e-4,
            json_schema_extra={
                "calibrable": Calibrable(
                    bounds=(1e-7, 1e-2),
                    transform="log",
                    prior="log_uniform",
                ),
            },
        )
    """

    bounds: tuple[float, float] | None = None
    transform: str = "identity"  # "identity" | "log" | "logit"
    prior: str = "uniform"  # "uniform" | "log_uniform" | "normal"
    units: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": list(self.bounds) if self.bounds else None,
            "transform": self.transform,
            "prior": self.prior,
            "units": self.units,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def _forward(transform: str, x: float) -> float:
    if transform == "identity":
        return x
    if transform == "log":
        if x <= 0.0:
            raise ValueError(f"log transform requires positive values, got {x}")
        return math.log10(x)
    if transform == "logit":
        if not (0.0 < x < 1.0):
            raise ValueError(f"logit transform requires 0<x<1, got {x}")
        return math.log(x / (1.0 - x))
    raise ValueError(f"Unknown transform: {transform!r}")


def _inverse(transform: str, y: float) -> float:
    if transform == "identity":
        return y
    if transform == "log":
        return 10.0**y
    if transform == "logit":
        return 1.0 / (1.0 + math.exp(-y))
    raise ValueError(f"Unknown transform: {transform!r}")


# ---------------------------------------------------------------------------
# CalibParameter + ParameterSpace
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibParameter:
    """A single calibration dimension resolved from TOML + annotations."""

    name: str
    lower: float
    upper: float
    transform: str = "identity"
    prior: str = "uniform"
    path: str | None = None  # dotted path into HydroModPyConfig (optional)
    units: str | None = None

    @property
    def lower_transformed(self) -> float:
        return _forward(self.transform, self.lower)

    @property
    def upper_transformed(self) -> float:
        return _forward(self.transform, self.upper)

    def to_physical(self, y: float) -> float:
        return _inverse(self.transform, y)

    def to_transformed(self, x: float) -> float:
        return _forward(self.transform, x)


class ParameterSpace:
    """Ordered collection of CalibParameter."""

    def __init__(self, parameters: Iterable[CalibParameter]):
        self._params = tuple(parameters)
        self._by_name = {p.name: p for p in self._params}
        if len(self._by_name) != len(self._params):
            raise ValueError("Duplicate parameter names in space")

    @property
    def dim(self) -> int:
        return len(self._params)

    @property
    def parameters(self) -> tuple[CalibParameter, ...]:
        return self._params

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self._params)

    def __getitem__(self, name: str) -> CalibParameter:
        return self._by_name[name]

    def __iter__(self):
        return iter(self._params)

    def __len__(self) -> int:
        return len(self._params)

    @property
    def transformed_bounds(self) -> dict[str, tuple[float, float]]:
        return {p.name: (p.lower_transformed, p.upper_transformed) for p in self._params}

    def physical_bounds(self) -> dict[str, tuple[float, float]]:
        return {p.name: (p.lower, p.upper) for p in self._params}

    @classmethod
    def from_toml_mapping(
        cls,
        declarations: Mapping[str, Mapping[str, Any]],
        *,
        annotations: Mapping[str, Calibrable] | None = None,
    ) -> "ParameterSpace":
        """Build a space from ``[calibration.parameters]`` TOML section.

        ``annotations`` may provide defaults harvested from Pydantic
        ``Calibrable`` hints keyed by parameter name. TOML overrides win.
        """
        annotations = annotations or {}
        params: list[CalibParameter] = []
        for name, decl in declarations.items():
            ann = annotations.get(name)
            bounds = decl.get("bounds")
            if bounds is None and ann is not None:
                bounds = ann.bounds
            if bounds is None:
                raise ValueError(f"Parameter {name!r} has no bounds (TOML or annotation)")
            low, high = float(bounds[0]), float(bounds[1])
            transform = decl.get("transform", ann.transform if ann else "identity")
            prior = decl.get("prior", ann.prior if ann else "uniform")
            units = decl.get("units", ann.units if ann else None)
            path = decl.get("path")
            params.append(
                CalibParameter(
                    name=name,
                    lower=low,
                    upper=high,
                    transform=transform,
                    prior=prior,
                    path=path,
                    units=units,
                )
            )
        return cls(params)


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------


def _iter_annotations(model_cls: type[BaseModel]) -> Iterable[tuple[str, Calibrable]]:
    for field_name, f in model_cls.model_fields.items():
        extra = f.json_schema_extra or {}
        if not isinstance(extra, dict):
            continue
        hint = extra.get("calibrable")
        if hint is None:
            continue
        if isinstance(hint, Calibrable):
            yield field_name, hint
        elif isinstance(hint, Mapping):
            yield (
                field_name,
                Calibrable(
                    bounds=tuple(hint["bounds"]) if hint.get("bounds") else None,
                    transform=hint.get("transform", "identity"),
                    prior=hint.get("prior", "uniform"),
                    units=hint.get("units"),
                    description=hint.get("description", ""),
                ),
            )


def discover_calibrable(
    config: BaseModel | type[BaseModel], *, _prefix: str = ""
) -> dict[str, Calibrable]:
    """Walk a Pydantic config tree and collect Calibrable annotations.

    Keys are dotted paths, e.g. ``"flow.properties.k_aquifer"``. Values are
    ``Calibrable`` metadata harvested from ``Field.json_schema_extra``.
    """
    cls = config if isinstance(config, type) else type(config)
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        return {}
    found: dict[str, Calibrable] = {}
    for field_name, hint in _iter_annotations(cls):
        key = f"{_prefix}{field_name}"
        found[key] = hint
    for field_name, f in cls.model_fields.items():
        sub_path = f"{_prefix}{field_name}."
        sub_cls = _resolve_submodel(f.annotation)
        if sub_cls is None:
            continue
        sub = getattr(config, field_name, None) if not isinstance(config, type) else None
        found.update(discover_calibrable(sub or sub_cls, _prefix=sub_path))
    return found


def _resolve_submodel(annotation: Any) -> type[BaseModel] | None:
    from typing import get_args, get_origin
    import types

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    if origin in (types.UnionType, getattr(__import__("typing"), "Union", None)):
        for arg in get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                return arg
    return None


# ---------------------------------------------------------------------------
# Apply resolved params to a config
# ---------------------------------------------------------------------------


def apply_values(
    base_config: BaseModel,
    values: Mapping[str, float],
    space: ParameterSpace,
) -> BaseModel:
    """Return a deep copy of ``base_config`` with calibrated values injected.

    Each CalibParameter with a ``path`` (dotted into the config tree) is set
    from ``values[name]``. Parameters without a path are ignored (useful for
    pure-Python calibration where the user handles injection manually).
    """
    cfg = base_config.model_copy(deep=True)
    for p in space:
        if p.path is None:
            continue
        if p.name not in values:
            continue
        _set_by_path(cfg, p.path, values[p.name])
    return cfg


def _set_by_path(cfg: BaseModel, path: str, value: float) -> None:
    parts = path.split(".")
    target: Any = cfg
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


__all__ = [
    "Calibrable",
    "CalibParameter",
    "ParameterSpace",
    "discover_calibrable",
    "apply_values",
]
