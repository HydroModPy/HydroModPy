"""Calibrable parameters: annotations, space, transforms, discovery.

A Pydantic field becomes calibrable by attaching a ``Calibrable`` instance via
``Field.json_schema_extra['calibrable']`` - or by being referenced in a TOML
``[calibration.parameters]`` block. Discovery walks a config tree and emits
``CalibParameter`` entries.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Calibrable:
    """Metadata attached to a Pydantic field to mark it calibrable.

    Usage::

        from hydromodpy.core.config_kit.field_metadata import field_metadata

        k_aquifer: float = Field(
            default=1e-4,
            json_schema_extra=field_metadata(
                calibrable=Calibrable(
                    bounds=(1e-7, 1e-2),
                    transform="log",
                    prior="log_uniform",
                ),
            ),
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
    """Resolved calibration dimension in physical and transformed space.

    The object combines user TOML declarations with optional ``Calibrable``
    field metadata. Bounds are stored in physical units, while helper
    properties expose transformed bounds for optimizers that sample in log or
    logit space.
    """

    name: str
    lower: float
    upper: float
    transform: str = "identity"
    prior: str = "uniform"
    path: str | None = None  # dotted path into HydroModPyConfig (optional)
    target: str | None = None  # readable alias for ``path`` (wins when set)
    mode: str = "replace"  # "replace" writes the sample; "scale" multiplies the base
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

    @property
    def effective_path(self) -> str | None:
        """Return ``target`` when set, else ``path``."""
        return self.target if self.target is not None else self.path


class ParameterSpace:
    """Ordered collection of calibrated parameters.

    The space preserves declaration order, exposes transformed bounds for
    optimizers, and can describe one candidate as serializable metadata for
    persistence and reporting.
    """

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

    def describe_values(self, values: Mapping[str, float]) -> dict[str, dict[str, Any]]:
        """Return serializable parameter metadata for one candidate."""
        out: dict[str, dict[str, Any]] = {}
        for param in self._params:
            if param.name not in values:
                continue
            physical = float(values[param.name])
            out[param.name] = {
                "value": physical,
                "transformed_value": param.to_transformed(physical),
                "bounds": [param.lower, param.upper],
                "transformed_bounds": [
                    param.lower_transformed,
                    param.upper_transformed,
                ],
                "transform": param.transform,
                "prior": param.prior,
                "mode": param.mode,
                "target": param.effective_path,
                "units": param.units,
            }
        return out

    def default_prior_mean_std(self) -> tuple[list[float], list[float]] | None:
        """Return Normal-prior vectors in transformed space when declared."""
        means: list[float] = []
        stds: list[float] = []
        has_normal = False
        for param in self._params:
            low = param.lower_transformed
            high = param.upper_transformed
            span = high - low
            if param.prior == "normal":
                has_normal = True
                means.append(0.5 * (low + high))
                stds.append(max(span / 6.0, 1e-12))
            else:
                means.append(0.5 * (low + high))
                stds.append(max(span * 1e6, 1e12))
        if not has_normal:
            return None
        return means, stds

    @classmethod
    def from_toml_mapping(
        cls,
        declarations: Mapping[str, Mapping[str, Any]],
        *,
        annotations: Mapping[str, Calibrable] | None = None,
    ) -> ParameterSpace:
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
            if not low < high:
                raise ValueError(f"Parameter {name!r}: lower bound must be < upper bound")
            if transform == "log" and low <= 0.0:
                raise ValueError(f"Parameter {name!r}: log transform requires lower > 0")
            if transform == "logit" and not (0.0 < low < high < 1.0):
                raise ValueError(
                    f"Parameter {name!r}: logit transform requires 0 < lower < upper < 1"
                )
            if prior not in {"uniform", "log_uniform", "normal"}:
                raise ValueError(f"Parameter {name!r}: unknown prior {prior!r}")
            if prior == "log_uniform" and low <= 0.0:
                raise ValueError(f"Parameter {name!r}: log_uniform prior requires lower > 0")
            units = decl.get("units", ann.units if ann else None)
            path = decl.get("path")
            target = decl.get("target")
            mode = str(decl.get("mode", "replace")).strip().lower()
            if mode not in {"replace", "scale"}:
                raise ValueError(
                    f"Parameter {name!r}: mode must be 'replace' or 'scale', got {mode!r}"
                )
            params.append(
                CalibParameter(
                    name=name,
                    lower=low,
                    upper=high,
                    transform=transform,
                    prior=prior,
                    path=path,
                    target=target,
                    mode=mode,
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
    import types
    from typing import get_args, get_origin

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


def apply_parameter_to_config(
    cfg: Any,
    param: CalibParameter,
    value: float,
) -> None:
    """Write ``value`` into ``cfg`` for ``param``, honouring ``param.mode``.

    ``mode="replace"`` writes the candidate value as-is at ``param.effective_path``.
    ``mode="scale"`` multiplies the existing value at that path by the candidate
    (the base value must be numeric).
    """
    path = param.effective_path
    if path is None:
        raise ValueError(f"Parameter {param.name!r} has no target or path")
    if param.mode == "replace":
        _set_by_path(cfg, path, float(value))
        return
    if param.mode == "scale":
        base = _get_by_path(cfg, path)
        if base is None:
            raise ValueError(
                f"Parameter {param.name!r}: scale mode requires a numeric base "
                f"value at {path!r}; resolved to None."
            )
        try:
            base_f = float(base)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Parameter {param.name!r}: scale mode requires a numeric base "
                f"value at {path!r}; got {base!r}."
            ) from exc
        _set_by_path(cfg, path, base_f * float(value))
        return
    raise ValueError(
        f"Parameter {param.name!r}: unsupported mode {param.mode!r} (expected 'replace' or 'scale')"
    )


def _set_by_path(cfg: Any, path: str, value: Any) -> None:
    """Set ``value`` at ``path`` on ``cfg``. Accepts Pydantic and Mapping."""
    parts = path.split(".")
    target: Any = cfg
    for part in parts[:-1]:
        if isinstance(target, Mapping):
            if part not in target:
                raise ValueError(f"Path segment {part!r} not found on {type(target).__name__}")
            target = target[part]
        else:
            if not hasattr(target, part):
                raise ValueError(f"Path segment {part!r} not found on {type(target).__name__}")
            target = getattr(target, part)
    leaf = parts[-1]
    if isinstance(target, Mapping):
        target[leaf] = value
    else:
        if not hasattr(target, leaf):
            raise ValueError(f"Leaf segment {leaf!r} not found on {type(target).__name__}")
        setattr(target, leaf, value)


def _get_by_path(cfg: Any, path: str) -> Any:
    """Return the value at dotted ``path`` on ``cfg`` or raise if missing."""
    parts = path.split(".")
    target: Any = cfg
    for part in parts:
        if isinstance(target, Mapping):
            if part not in target:
                raise ValueError(f"Path segment {part!r} not found on {type(target).__name__}")
            target = target[part]
        else:
            if not hasattr(target, part):
                raise ValueError(f"Path segment {part!r} not found on {type(target).__name__}")
            target = getattr(target, part)
    return target


__all__ = [
    "Calibrable",
    "CalibParameter",
    "ParameterSpace",
    "discover_calibrable",
    "apply_parameter_to_config",
]
