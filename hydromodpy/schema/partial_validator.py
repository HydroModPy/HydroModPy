"""Partial field validator for the HydroModPy configuration.

Given a dotted ``field_path`` (e.g. ``flow.properties.specific_yield``) and
a candidate ``value``, :func:`validate_field` returns a lightweight
``ValidationResult`` that a frontend can surface while the user types.

The implementation navigates the Pydantic root model to find the leaf
field, then re-validates the value via :class:`pydantic.TypeAdapter`. This
avoids building a full ``PartialHydroModPyConfig`` per request and keeps
the per-call cost well below the 50 ms target stated in
``architecture_cible/11_frontend_ready.md``.

The validator never needs network or disk I/O; it is safe to call
repeatedly from an interactive UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single configuration field."""

    valid: bool
    path: str
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    dependent_fields_affected: list[str] = field(default_factory=list)
    timing_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split_path(path: str) -> list[str]:
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise ValueError(f"empty field path: {path!r}")
    return parts


def _root_model() -> type[BaseModel]:
    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

    return HydroModPyConfig


def _resolve_field(path: str) -> tuple[type[BaseModel], str, FieldInfo]:
    """Walk the root model and return ``(owner_cls, leaf_name, FieldInfo)``."""
    parts = _split_path(path)
    current: type[BaseModel] = _root_model()
    for name in parts[:-1]:
        if name not in current.model_fields:
            raise KeyError(f"unknown field {name!r} while resolving {path!r} in {current.__name__}")
        annotation = current.model_fields[name].annotation
        nested = _unwrap_basemodel(annotation)
        if nested is None:
            # Mid-path points to a leaf (e.g. dict[str, float]); bail out
            # and let caller treat as a dynamic payload.
            raise KeyError(f"mid-path field {name!r} in {path!r} is not a nested model")
        current = nested

    leaf = parts[-1]
    if leaf not in current.model_fields:
        raise KeyError(f"unknown leaf {leaf!r} in {current.__name__}")
    return current, leaf, current.model_fields[leaf]


def _unwrap_basemodel(annotation: Any) -> type[BaseModel] | None:
    """Return the inner BaseModel class of an annotation or ``None``."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in getattr(annotation, "__args__", ()) or ():
        inner = _unwrap_basemodel(arg)
        if inner is not None:
            return inner
    return None


@lru_cache(maxsize=512)
def _adapter_for(path: str) -> TypeAdapter:
    _, _, info = _resolve_field(path)
    return TypeAdapter(info.annotation)


def _format_error(exc: ValidationError) -> str:
    details = exc.errors(include_url=False, include_context=False)
    if not details:
        return str(exc)
    first = details[0]
    msg = first.get("msg", "invalid value")
    ctx = first.get("ctx") or {}
    if ctx:
        parts = [f"{k}={v}" for k, v in ctx.items()]
        return f"{msg} ({', '.join(parts)})"
    return msg


def _collect_dependents(path: str) -> list[str]:
    """Return other field paths statically known to depend on *path*.

    The current implementation returns an empty list because HydroModPy
    does not yet declare cross-field links. It preserves the shape of the
    spec so the frontend can already consume the response.
    """
    return []


def validate_field(
    path: str,
    value: Any,
    context: dict[str, Any] | None = None,
    locale: str = "en",
) -> ValidationResult:
    """Validate ``value`` against the type of ``path`` in ``HydroModPyConfig``.

    Parameters
    ----------
    path
        Dotted field path (e.g. ``"flow.properties.k_aquifer"``).
    value
        Candidate value to validate.
    context
        Optional dict mirroring the form state. Currently unused by the
        per-field check; accepted so the signature is stable across the
        future partial-model implementation.
    locale
        Reserved for localization; the Pydantic error message is returned
        as-is for now.
    """
    from time import perf_counter

    t0 = perf_counter()
    # Both `context` and `locale` are part of the documented signature and
    # will be consumed once partial-model validation lands; the underscore
    # assignments keep linters happy without reshaping the public API.
    _ = context, locale
    try:
        adapter = _adapter_for(path)
    except KeyError as exc:
        elapsed = (perf_counter() - t0) * 1000.0
        return ValidationResult(
            valid=False,
            path=path,
            error=str(exc),
            timing_ms=elapsed,
        )

    try:
        adapter.validate_python(value)
    except ValidationError as exc:
        elapsed = (perf_counter() - t0) * 1000.0
        return ValidationResult(
            valid=False,
            path=path,
            error=_format_error(exc),
            dependent_fields_affected=_collect_dependents(path),
            timing_ms=elapsed,
        )
    except (TypeError, ValueError) as exc:
        elapsed = (perf_counter() - t0) * 1000.0
        return ValidationResult(
            valid=False,
            path=path,
            error=str(exc),
            dependent_fields_affected=_collect_dependents(path),
            timing_ms=elapsed,
        )

    elapsed = (perf_counter() - t0) * 1000.0
    return ValidationResult(
        valid=True,
        path=path,
        dependent_fields_affected=_collect_dependents(path),
        timing_ms=elapsed,
    )


__all__ = ["validate_field", "ValidationResult"]
