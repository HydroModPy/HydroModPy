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

# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


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


_MESH_SECTIONS: tuple[str, ...] = ("mesh_catchment", "mesh_catchment_batch", "mesh_input")


def _assert_path_is_not_the_mesh(name: str, path: str | None) -> None:
    """Refuse a parameter that would search over the mesh itself.

    Two reasons, and either one is enough. The stream-network criterion is
    normalised by cell size, so refining the mesh moves the yardstick and a
    search that optimises it is circular. And the mesh step reads the mesh
    sections resolved once from the raw file rather than the per-trial
    configuration, so the value would never reach the mesh: every trial would
    score the same model under a different number.

    A mesh question is answered by a sweep, not by a search: one run per mesh,
    compared, and read for convergence.
    """
    if not path:
        return
    head = str(path).split(".", 1)[0]
    if head not in _MESH_SECTIONS:
        return
    raise ValueError(
        f"[calibration.parameters.{name}] points at {path!r}, and the mesh is not a "
        "parameter a search may move: the stream-network criterion is normalised by "
        "cell size, so refining the mesh moves the yardstick the search is scored "
        "against. Run one simulation per mesh and compare them instead "
        '(workflow mode = "comparison", `hmp run`), which reads them for '
        "convergence rather than for a best score."
    )


_STAGE_BOUNDARY_PATHS: tuple[str, ...] = (
    "flow.flow_regime",
    "simulation.time.start_datetime",
    "simulation.time.end_datetime",
    "simulation.time.step_value",
    "simulation.time.step_unit",
    "simulation.time.substeps_per_period",
)
"""Paths that say WHICH MODEL a stage runs, rather than a property of one."""


def _assert_path_is_not_a_stage_boundary(name: str, path: str | None) -> None:
    """Refuse a parameter that would search over the stage instead of the model.

    A flow regime and a simulation window are not properties of the aquifer:
    they say which model a stage runs. A phase declares them in its own
    ``overrides``, which is where a two-stage method makes one stage steady and
    the other transient. Searching over one asks the optimizer to choose between
    two different models on a cost that only ever compares trials of one, and a
    regime is categorical besides: every candidate is written through
    ``float(value)``, so the search would put 0.5 into a field whose two legal
    values are two words.
    """
    if not path:
        return
    if str(path) not in _STAGE_BOUNDARY_PATHS:
        return
    raise ValueError(
        f"[calibration.parameters.{name}] points at {path!r}, which is a stage boundary "
        "and not a dimension a search may move: it says which model the stage runs, not "
        "a property of that model. Declare it in a phase's [calibration.phases.overrides] "
        "instead, which is how a two-stage method makes one stage steady and the next "
        "transient."
    )


def _assert_bounds_are_physical(name: str, low: float, high: float, unit: object) -> None:
    """Face a declared bound with the ceiling a literal value already faces.

    The registry refuses a specific yield of 0.8 written in ``[flow.param]`` and
    never saw the bounds a calibration searches between, so the same value passed
    unnoticed there. Checking the bounds rather than each sample refuses the whole
    impossible region once, before the first solve. An id the registry does not
    know is left alone, exactly as it is everywhere else.
    """
    from hydromodpy.spatial.field.core.physical_bounds import (
        PhysicalBoundsError,
        validate_physical_value,
    )

    unit_text = str(unit) if unit is not None else None
    for edge, value in (("lower", low), ("upper", high)):
        try:
            validate_physical_value(param_id=name, value=value, unit=unit_text)
        except PhysicalBoundsError as exc:
            raise ValueError(
                f"[calibration.parameters.{name}] {edge} bound {value!r}: {exc}"
            ) from None


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
    ) -> ParameterSpace:
        """Build a space from ``[calibration.parameters]`` TOML section.

        What a field declares about itself has already been written into the
        declaration by :mod:`hydromodpy.calibration.parameter_resolution`, so
        there is one place where a default can come from and it is upstream of
        here.
        """
        params: list[CalibParameter] = []
        for name, decl in declarations.items():
            bounds = decl.get("bounds")
            if bounds is None:
                raise ValueError(f"Parameter {name!r} has no bounds")
            low, high = float(bounds[0]), float(bounds[1])
            transform = decl.get("transform", "identity")
            prior = decl.get("prior", "uniform")
            if not low < high:
                raise ValueError(f"Parameter {name!r}: lower bound must be < upper bound")
            if transform == "log" and low <= 0.0:
                raise ValueError(f"Parameter {name!r}: log transform requires lower > 0")
            if transform == "logit" and not (0.0 < low < high < 1.0):
                raise ValueError(
                    f"Parameter {name!r}: logit transform requires 0 < lower < upper < 1"
                )
            path = decl.get("path")
            target = decl.get("target")
            _assert_bounds_are_physical(name, low, high, decl.get("units"))
            if prior not in {"uniform", "log_uniform", "normal"}:
                raise ValueError(f"Parameter {name!r}: unknown prior {prior!r}")
            if prior == "log_uniform" and low <= 0.0:
                raise ValueError(f"Parameter {name!r}: log_uniform prior requires lower > 0")
            units = decl.get("units")
            _assert_path_is_not_the_mesh(name, path)
            _assert_path_is_not_the_mesh(name, target)
            _assert_path_is_not_a_stage_boundary(name, path)
            _assert_path_is_not_a_stage_boundary(name, target)
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
    try:
        _apply_resolved(cfg, param, path, value)
    except ValueError as exc:
        # Name the TOML key that declared the path: the walk only knows the path.
        raise ValueError(f"[calibration.parameters.{param.name}] {exc}") from None


def _assert_candidate_is_physical(param: CalibParameter, written: float) -> None:
    """Face the value about to be written with the registry's ceiling.

    Checking the declared bounds at load time refuses the impossible region
    once, and that covers ``mode="replace"``. It does not cover ``mode="scale"``,
    where the sample is a multiplier: legal bounds on the multiplier say nothing
    about where the product lands, so a scale of 8 on a specific yield of 0.1
    writes 0.8, past the physical ceiling, and only the solver would notice.

    Keyed on the parameter's own name. A value reached through a resolved name
    is already faced with the range its catalogue entry carries, at load time,
    in :mod:`hydromodpy.calibration.parameter_resolution`; what is left here is
    the best a bare name can do.
    """
    from hydromodpy.spatial.field.core.physical_bounds import (
        PhysicalBoundsError,
        validate_physical_value,
    )

    unit_text = str(param.units) if param.units is not None else None
    try:
        validate_physical_value(param_id=param.name, value=written, unit=unit_text)
    except PhysicalBoundsError as exc:
        raise ValueError(f"candidate {written!r}: {exc}") from None


def _apply_resolved(cfg: Any, param: CalibParameter, path: str, value: float) -> None:
    if param.mode == "replace":
        _assert_candidate_is_physical(param, float(value))
        set_by_path(cfg, path, float(value))
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
        written = base_f * float(value)
        _assert_candidate_is_physical(param, written)
        set_by_path(cfg, path, written)
        return
    raise ValueError(
        f"Parameter {param.name!r}: unsupported mode {param.mode!r} (expected 'replace' or 'scale')"
    )


def _unknown_segment(path: str, part: str, depth: int, target: Any) -> ValueError:
    """Say which segment of which path is wrong, and what was there instead.

    The reader wrote the path in a TOML and has never seen the Python class the
    walk reached, so the class name is the last thing in the message rather than
    its subject.
    """
    reached = ".".join(path.split(".")[:depth]) or "the configuration root"
    if isinstance(target, Mapping):
        available = sorted(str(key) for key in target)
    else:
        available = sorted(k for k in vars(type(target)).get("model_fields", ()) or ())
        if not available:
            available = sorted(k for k in vars(target) if not k.startswith("_"))
    known = ", ".join(available[:12]) if available else "nothing"
    return ValueError(
        f"{path!r}: no {part!r} under {reached}, which holds {known} ({type(target).__name__})."
    )


def set_by_path(cfg: Any, path: str, value: Any) -> None:
    """Set ``value`` at ``path`` on ``cfg``. Accepts Pydantic and Mapping."""
    parts = path.split(".")
    target: Any = cfg
    for depth, part in enumerate(parts[:-1]):
        if isinstance(target, Mapping):
            if part not in target:
                raise _unknown_segment(path, part, depth, target)
            target = target[part]
        else:
            if not hasattr(target, part):
                raise _unknown_segment(path, part, depth, target)
            target = getattr(target, part)
    leaf = parts[-1]
    if isinstance(target, Mapping):
        target[leaf] = value
    else:
        if not hasattr(target, leaf):
            raise _unknown_segment(path, leaf, len(parts) - 1, target)
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
    "CalibParameter",
    "ParameterSpace",
    "apply_parameter_to_config",
    "set_by_path",
]
