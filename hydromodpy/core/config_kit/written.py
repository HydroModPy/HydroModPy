"""What a configuration was given, as opposed to the defaults it took.

Pydantic keeps the fields a model was given in ``model_fields_set``, and a
validator may read it to tell a key the file wrote from its default. A copy
of the configuration that spells out every default turns every default into a
written key, and such a validator then answers otherwise: it refuses a key the
file never wrote, or takes the default where the file was silent. The copy
written here leaves out the defaults nobody gave, so it validates into the same
model, with the same fields set.

The same reading tells which experimental keys a configuration wrote, so a run
can say so without a default ever counting.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from functools import cache
from typing import Annotated, Any, Literal, get_args, get_origin

from pydantic import BaseModel, TypeAdapter

from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE

logger = get_logger(__name__)


def written_fields(model: BaseModel) -> tuple[str, ...]:
    """Return the fields of *model* that are not a default taken in silence.

    A field counts when the file, a caller or the run set it, or when it holds
    a value other than its default: a validator that derives one field from
    another (``step_value = "7 days"`` gives ``step_unit``), or a value set
    under a section the file never wrote. The tag of a model (a field that
    admits one literal) always counts, since a union reads the model by it.
    """
    return tuple(
        name
        for name, info in type(model).model_fields.items()
        if name in model.model_fields_set
        or _is_tag(info.annotation)
        or not _holds_its_default(model, name)
    )


def written_payload(model: BaseModel) -> dict[str, Any]:
    """Return ``model.model_dump(mode="json")`` cut down to its written fields, at every depth."""
    pruned = _prune(model, model.model_dump(mode="json"))
    assert isinstance(pruned, dict)
    return pruned


def written_experimental_keys(model: BaseModel) -> tuple[str, ...]:
    """Return the experimental keys *model* was given, as dotted paths, in field order.

    A key counts the way :func:`written_fields` counts it, so a default taken in
    silence gives nothing. A marked section is one entry and the walk stops
    there, since the mark covers what is below it. A selector counts when it holds
    a marked value, and its entry names the value.
    """
    return tuple(_experimental_keys(model, ""))


def experimental_keys_line(keys: Sequence[str]) -> str:
    """Return the one line that tells a user which experimental keys are in use."""
    return f"Experimental keys in use, they may change in a minor release: {', '.join(keys)}"


def log_experimental_keys(model: BaseModel) -> None:
    """Log that line once, when *model* wrote an experimental key."""
    keys = written_experimental_keys(model)
    if keys:
        logger.info("%s", experimental_keys_line(keys), extra=MILESTONE)


def _experimental_keys(value: Any, path: str) -> Iterator[str]:
    if isinstance(value, BaseModel):
        for name in written_fields(value):
            key = f"{path}.{name}" if path else name
            extra = type(value).model_fields[name].json_schema_extra
            extra = extra if isinstance(extra, dict) else {}
            held = getattr(value, name)
            if held is None:
                # TOML has no null: a loader that fills a section it did not find
                # sets the field, and the file wrote nothing.
                continue
            if extra.get("stability") == "experimental":
                yield key
                continue
            marked = extra.get("experimental_values", ())
            for item in held if isinstance(held, (list, tuple)) else (held,):
                if isinstance(item, str) and item in marked:
                    yield f'{key} = "{item}"'
            yield from _experimental_keys(held, key)
    elif isinstance(value, Mapping):
        for name, item in value.items():
            yield from _experimental_keys(item, f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _experimental_keys(item, f"{path}[{index}]")


def _is_tag(annotation: Any) -> bool:
    return get_origin(annotation) is Literal and len(get_args(annotation)) == 1


def _holds_its_default(model: BaseModel, name: str) -> bool:
    """Whether the field holds its default, as the field type validates it.

    A default is stored as written in the class (``2.0`` for a length) and
    validated only when taken (``2.0 m``), so the raw default never equals
    the value. A default that cannot be built or compared counts as departed
    from: the copy then says more than needed, never less.
    """
    info = type(model).model_fields[name]
    value = getattr(model, name)
    try:
        default = info.get_default(call_default_factory=True, validated_data=dict(model.__dict__))
        if _same(value, default):
            return True
        return _same(value, _field_adapter(type(model), name).validate_python(default))
    except Exception:
        return False


@cache
def _field_adapter(cls: type[BaseModel], name: str) -> TypeAdapter[Any]:
    info = cls.model_fields[name]
    return TypeAdapter(Annotated[info.annotation, *info.metadata])


def _same(value: Any, other: Any) -> bool:
    """Compare two configuration values by what they hold, private marks aside."""
    if isinstance(value, BaseModel) or isinstance(other, BaseModel):
        return type(value) is type(other) and value.model_dump() == other.model_dump()
    if isinstance(value, Mapping) and isinstance(other, Mapping):
        return value.keys() == other.keys() and all(_same(value[k], other[k]) for k in value)
    if isinstance(value, (list, tuple)) and isinstance(other, (list, tuple)):
        return len(value) == len(other) and all(map(_same, value, other))
    return bool(value == other)


def _prune(value: Any, dumped: Any) -> Any:
    """Return *dumped* restricted to what *value* was given, where both have the same shape."""
    if isinstance(value, BaseModel) and isinstance(dumped, Mapping):
        return {
            name: _prune(getattr(value, name), dumped[name])
            for name in written_fields(value)
            if name in dumped
        }
    if isinstance(value, Mapping) and isinstance(dumped, Mapping) and len(value) == len(dumped):
        return {
            key: _prune(item, dumped_item)
            for item, (key, dumped_item) in zip(value.values(), dumped.items(), strict=True)
        }
    if isinstance(value, (list, tuple)) and isinstance(dumped, list) and len(value) == len(dumped):
        return [_prune(item, dumped_item) for item, dumped_item in zip(value, dumped, strict=True)]
    return dumped


__all__ = [
    "experimental_keys_line",
    "log_experimental_keys",
    "written_experimental_keys",
    "written_fields",
    "written_payload",
]
