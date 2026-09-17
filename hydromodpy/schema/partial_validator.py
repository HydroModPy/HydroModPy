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
from typing import Any, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import iter_basemodels


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
    from hydromodpy.config import HydroModPyConfig

    return HydroModPyConfig


def _resolve_field(path: str) -> tuple[type[BaseModel], str, FieldInfo]:
    """Walk the root model and return ``(owner_cls, leaf_name, FieldInfo)``.

    When a mid-path field is a discriminated union of BaseModels, this helper
    searches every variant for the next path segment and picks the one that
    declares it. That avoids the false-positive a naive "take the first
    BaseModel" strategy would produce when only one variant declares the leaf.
    """
    parts = _split_path(path)
    candidates: list[type[BaseModel]] = [_root_model()]
    skip_next = False
    for index, name in enumerate(parts[:-1]):
        if skip_next:
            # The segment before this one was a mapping of models, so this one
            # is a key the user chose (a parameter id, a boundary id, a support)
            # and not a field any model declares. Looking it up would refuse
            # every path a calibration actually writes.
            skip_next = False
            continue
        next_candidates: list[type[BaseModel]] = []
        seen: set[type[BaseModel]] = set()
        for cls in candidates:
            if name not in cls.model_fields:
                continue
            annotation = cls.model_fields[name].annotation
            if _is_mapping_of_models(annotation):
                skip_next = True
            for nested in iter_basemodels(annotation):
                if nested in seen:
                    continue
                seen.add(nested)
                next_candidates.append(nested)
        if not next_candidates:
            current_name = candidates[0].__name__ if candidates else "?"
            raise KeyError(f"unknown field {name!r} while resolving {path!r} in {current_name}")
        candidates = next_candidates
        del index

    leaf = parts[-1]
    if skip_next:
        # The path stops on the instance itself, which is a whole model rather
        # than one of its values; there is no leaf type to validate against.
        raise KeyError(f"{path!r} names an entry, not one of its values")
    for cls in candidates:
        if leaf in cls.model_fields:
            return cls, leaf, cls.model_fields[leaf]
    raise KeyError(f"unknown leaf {leaf!r} in {candidates[0].__name__}")


def _is_mapping_of_models(annotation: Any) -> bool:
    """Return whether ``annotation`` is a mapping whose values are models.

    A mapping is where an instance lives: the key is a name the user chose, so
    the segment after it belongs to the value type and not to the mapping.
    """
    from collections.abc import Mapping as MappingABC

    for node in (annotation, *(getattr(annotation, "__args__", ()) or ())):
        origin = get_origin(node)
        if origin is None:
            continue
        if not (isinstance(origin, type) and issubclass(origin, (dict, MappingABC))):
            continue
        args = getattr(node, "__args__", ()) or ()
        if len(args) == 2 and iter_basemodels(args[1]):
            return True
    return False


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
