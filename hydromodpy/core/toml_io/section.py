"""Walk a Pydantic model and write its ``[section]`` of the TOML template.

A section is written in four steps: single-field containers are flattened,
the fields are sorted into scalars, nested models and lists of models, then
each group is emitted in that order. The settings every step shares (profile
threshold, depth, commented-out mode, instance mode) travel in one frozen
:class:`_Ctx`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, get_args

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import iter_fields_by_profile
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
from hydromodpy.core.toml_io.model_types import (
    is_mapping_field,
    resolve_basemodel_type,
    resolve_list_basemodel_type,
    resolve_mapping_basemodel_types,
    variant_for_values,
    variant_tag_field,
)
from hydromodpy.core.toml_io.render import (
    UNDEFINED,
    append_comment_text,
    declares_nothing,
    default_value,
    factory_value,
    fmt,
    fmt_key,
    is_disabled,
    is_implicit_relative_path_default,
    placeholder,
    render_field_comment,
    render_mapping_value,
    toml_excluded,
)

_RULE = "# " + "-" * 70

_ScalarField = tuple[str, FieldInfo, Profile]
_ModelField = tuple[str, FieldInfo, Profile, type[BaseModel]]


@dataclass(frozen=True)
class _Ctx:
    """What every step of one section shares.

    ``depth`` is 0 for a top-level section, which alone gets a banner.
    ``commented`` prefixes every line with ``# `` (an Optional sub-table with
    no override). ``from_instance`` says the values are a whole config rather
    than partial overrides, so a field they do not carry is a field that is not
    set: a template entry written for it would be a placeholder the reload
    refuses.
    """

    threshold: int
    depth: int = 0
    commented: bool = False
    from_instance: bool = False

    def line(self, text: str) -> str:
        return f"# {text}" if self.commented else text

    def child(self, *, commented: bool) -> _Ctx:
        return replace(self, depth=self.depth + 1, commented=commented)


def section(
    section_name: str,
    model_cls: type[BaseModel],
    threshold: int,
    values: dict | None = None,
    *,
    from_instance: bool = False,
) -> list[str]:
    """Generate a top-level [section] with filtered fields, banner included.

    Parameters
    ----------
    values : dict or None
        When provided, these values override defaults for the value line.
        A ``None`` entry means the field is left commented out.
    from_instance : bool
        When True, *values* are a whole config rather than partial overrides.
    """
    ctx = _Ctx(threshold, from_instance=from_instance)
    return _emit_section(ctx, section_name, model_cls, values)


def _emit_section(
    ctx: _Ctx, section_name: str, model_cls: type[BaseModel], values: dict | None
) -> list[str]:
    flattened = _flattened(model_cls, values)
    if flattened is not None:
        inner_cls, inner_values = flattened
        return _emit_section(ctx, section_name, inner_cls, inner_values)

    scalars, nested, arrays = _classify_fields(model_cls, ctx.threshold)
    lines: list[str] = []
    if ctx.depth == 0:
        title = (model_cls.__doc__ or section_name).strip().split("\n")[0]
        lines.extend(["", _RULE, f"# {title}", _RULE])

    if scalars:
        disabled = is_disabled(model_cls, values)
        lines.extend(_emit_scalars(ctx, section_name, scalars, values, disabled))
    elif not nested and not arrays:
        lines.extend(
            [
                "",
                ctx.line(f"[{section_name}]"),
                "# (no parameters at this profile level)",
                "",
            ]
        )
    lines.extend(_emit_nested(ctx, section_name, nested, values))
    lines.extend(_emit_arrays(ctx, section_name, arrays, values))
    return lines


def _flattened(
    model_cls: type[BaseModel], values: dict | None
) -> tuple[type[BaseModel], dict | None] | None:
    """Return the inner model and values of a ``toml_flatten`` container.

    A model with ``toml_flatten = True`` (ClassVar) skips one nesting level: its
    first model field is written at the container's own section name, so
    ``FlowInitialConditions.h`` renders as ``[flow.ic]`` and not
    ``[flow.ic.h]``. ``None`` when the model is not such a container.
    """
    if not getattr(model_cls, "toml_flatten", False):
        return None
    for name, field_info in model_cls.model_fields.items():
        inner_cls = resolve_basemodel_type(field_info)
        if inner_cls is not None:
            inner_values = _values_of(values, name)
            return variant_for_values(field_info, inner_cls, inner_values), inner_values
    return None


def _values_of(values: dict | None, name: str) -> dict | None:
    """Return the dict *values* holds for the sub-table *name*, if any."""
    if values is None or name not in values:
        return None
    raw = values[name]
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    return None


def _classify_fields(
    model_cls: type[BaseModel], threshold: int
) -> tuple[list[_ScalarField], list[_ModelField], list[_ModelField]]:
    """Sort the visible fields into scalars, nested models and lists of models."""
    scalars: list[_ScalarField] = []
    nested: list[_ModelField] = []
    arrays: list[_ModelField] = []
    for name, field_info, level in iter_fields_by_profile(model_cls, threshold):
        # Fields excluded from serialization (e.g. Transport) have no line.
        if toml_excluded(field_info):
            continue
        list_cls = resolve_list_basemodel_type(field_info)
        if list_cls is not None:
            arrays.append((name, field_info, level, list_cls))
            continue
        nested_cls = resolve_basemodel_type(field_info)
        if nested_cls is not None:
            nested.append((name, field_info, level, nested_cls))
        else:
            scalars.append((name, field_info, level))
    return scalars, nested, arrays


def _emit_scalars(
    ctx: _Ctx,
    section_name: str,
    scalars: list[_ScalarField],
    values: dict | None,
    disabled: bool,
) -> list[str]:
    """Write ``[section]`` and its scalar keys, then the mappings set aside."""
    lines = ["", ctx.line(f"[{section_name}]")]
    deferred_mappings: list[tuple[str, dict[str, Any]]] = []
    deferred_skeletons: list[tuple[str, FieldInfo]] = []

    for name, field_info, level in scalars:
        given = values is not None and name in values and values[name] is not None
        if given and is_implicit_relative_path_default(values[name], field_info):
            continue
        render_field_comment(lines, field_info)
        default = default_value(field_info)

        if given:
            raw_value = values[name]
            if isinstance(raw_value, BaseModel):
                raw_value = raw_value.model_dump(exclude_none=True)
            if isinstance(raw_value, dict):
                deferred_mappings.append((name, raw_value))
            else:
                lines.append(ctx.line(f"{name} = {fmt(raw_value)}"))
        elif is_mapping_field(field_info):
            # A mapping with no concrete value is written as sub-tables, never
            # as an inline ``name = {}``: an inline table cannot be extended by
            # later ``[section.name.<id>]`` sub-tables, which is invalid TOML.
            if isinstance(default, dict) and default:
                deferred_mappings.append((name, default))
            elif resolve_mapping_basemodel_types(field_info):
                deferred_skeletons.append((name, field_info))
            else:
                lines.append(f"# {name}: entries go under [{section_name}.{name}.<id>]")
        else:
            lines.append(_unset_scalar_line(ctx, name, field_info, level, values, disabled))
        lines.append("")

    for name, mapping_value in deferred_mappings:
        lines.extend(
            render_mapping_value(f"{section_name}.{name}", mapping_value, _commented=ctx.commented)
        )
    for name, skeleton_field in deferred_skeletons:
        lines.extend(
            _mapping_entry_skeleton(f"{section_name}.{name}.<id>", skeleton_field, ctx.threshold)
        )
    return lines


def _unset_scalar_line(
    ctx: _Ctx,
    name: str,
    field_info: FieldInfo,
    level: Profile,
    values: dict | None,
    disabled: bool,
) -> str:
    """Return the value line of a scalar the caller gave no value for."""
    default = default_value(field_info)
    if ctx.from_instance and values is not None and name not in values:
        # The dump left this key out (it holds its default): writing it would
        # make the reload read it as written.
        return f"# {name} = {fmt(default)}" if default is not None else f"# {name} ="
    if default is not UNDEFINED and default is not None:
        return ctx.line(f"{name} = {fmt(default)}")
    from_factory = factory_value(field_info)
    if from_factory is not None:
        return ctx.line(f"{name} = {fmt(from_factory)}")
    if level == Profile.USER and default is UNDEFINED:
        # A required field of a disabled section stays commented: the section
        # validates without it, and a placeholder would be refused. Otherwise a
        # user-level required field gets an uncommented placeholder to fill in.
        line = f"{name} = {placeholder(field_info)}"
        return f"# {line}" if disabled else ctx.line(line)
    # Optional field with default=None, or non-user field with no concrete
    # default: a commented-out placeholder.
    return f"# {name} = {placeholder(field_info)}" if default is None else f"# {name} ="


def _emit_description(lines: list[str], field_info: FieldInfo) -> None:
    """Write the field description, after a blank line, as comment lines."""
    desc = field_info.description or ""
    if desc:
        lines.append("")
        append_comment_text(lines, desc)


def _emit_nested(
    ctx: _Ctx, section_name: str, nested: list[_ModelField], values: dict | None
) -> list[str]:
    """Write each nested model as a sub-table of *section_name*."""
    lines: list[str] = []
    for name, field_info, _level, nested_cls in nested:
        sub_section = f"{section_name}.{name}"
        sub_values = _values_of(values, name)
        nested_cls = variant_for_values(field_info, nested_cls, sub_values)
        is_truly_optional = default_value(field_info) is None and field_info.default_factory is None
        _emit_description(lines, field_info)
        if is_truly_optional and sub_values is None:
            # Optional with no override: expand commented out.
            lines.extend(_emit_section(ctx.child(commented=True), sub_section, nested_cls, None))
        else:
            # A default_factory or a concrete override: expand as is.
            lines.extend(
                _emit_section(
                    ctx.child(commented=ctx.commented), sub_section, nested_cls, sub_values
                )
            )
    return lines


def _emit_arrays(
    ctx: _Ctx, section_name: str, arrays: list[_ModelField], values: dict | None
) -> list[str]:
    """Write each list of models as ``[[section.name]]`` blocks."""
    lines: list[str] = []
    for name, field_info, _level, item_cls in arrays:
        _emit_description(lines, field_info)
        has_instance_value = values is not None and name in values
        items: list[dict] | None = None
        if has_instance_value and isinstance(values[name], list):
            items = values[name]
        lines.extend(
            _array_of_tables(
                ctx,
                f"{section_name}.{name}",
                field_info,
                item_cls,
                items=items,
                has_instance_value=has_instance_value,
            )
        )
    return lines


def _variant_tag_line(model_cls: type[BaseModel]) -> str | None:
    """Return the ``key = "value"`` line a union member pins itself with."""
    name = variant_tag_field(model_cls)
    if name is None:
        return None
    return f'{name} = "{get_args(model_cls.model_fields[name].annotation)[0]}"'


def _mapping_entry_skeleton(
    sub_section: str,
    field_info: FieldInfo,
    threshold: int,
) -> list[str]:
    """Render one commented example entry for a mapping of models.

    A template carries no entry for a mapping the reader keys itself, so a bare
    pointer line leaves the shape invisible. Show the table to write and the
    fields of one variant instead. Variants share that one table and pick their
    shape with a key inside it, so the others are listed, not repeated.
    """
    variants = resolve_mapping_basemodel_types(field_info)
    if not variants:
        return []
    lines = ["", f"# Example entry, one [{sub_section}] table per entry."]
    tags = [tag for tag in (_variant_tag_line(variant) for variant in variants) if tag]
    if len(tags) > 1:
        lines.append(f"# Shown with {tags[0]}. Other variants: {', '.join(tags[1:])}.")
    lines.append(f"# [{sub_section}]")
    for name, info, _level in iter_fields_by_profile(variants[0], threshold):
        if toml_excluded(info):
            continue
        render_field_comment(lines, info)
        default = default_value(info)
        if default is not UNDEFINED and default is not None:
            lines.append(f"# {name} = {fmt(default)}")
        else:
            lines.append(f"# {name} = {placeholder(info)}")
    lines.append("")
    return lines


def _array_of_tables(
    ctx: _Ctx,
    table: str,
    field_info: FieldInfo | None,
    item_cls: type[BaseModel],
    *,
    items: list[dict] | None,
    has_instance_value: bool,
) -> list[str]:
    """Render the ``[[table]]`` blocks of a repeated table, or one example entry."""
    lines: list[str] = []
    if items:
        for item_dict in items:
            lines.append(ctx.line(f"[[{table}]]"))
            for key, val in item_dict.items():
                if key in item_cls.model_fields:
                    render_field_comment(lines, item_cls.model_fields[key])
                if val is None:
                    # TOML has no null, so ``key =`` is not a line; the key
                    # stays out and reload restores the default it holds.
                    lines.append(f"# {key} =")
                else:
                    lines.append(ctx.line(f"{fmt_key(key)} = {fmt(val)}"))
                lines.append("")
        return lines
    if has_instance_value or ctx.from_instance:
        # A config that does not carry this table does not want it; the
        # example entry below is a template gesture, and its placeholders
        # are not values a reload accepts.
        return lines

    # Template mode: show an example entry with defaults. A table the model
    # does not declare by itself stays commented out: writing it is what turns
    # the feature on, so a template must not do it for the reader.
    optional = field_info is None or declares_nothing(field_info)
    if optional:
        lines.append(f"# Example entry, one [[{table}]] block per entry.")
    emit = _commented_line if optional else ctx.line
    lines.append(emit(f"[[{table}]]"))
    for fname, finfo, _flevel in iter_fields_by_profile(item_cls, ctx.threshold):
        if toml_excluded(finfo):
            continue
        render_field_comment(lines, finfo)
        default = default_value(finfo)
        if default is not UNDEFINED and default is not None:
            lines.append(emit(f"{fname} = {fmt(default)}"))
        else:
            lines.append(emit(f"{fname} = {placeholder(finfo)}"))
        lines.append("")
    return lines


def _commented_line(text: str) -> str:
    return f"# {text}"


def repeated_root_section(
    section_name: str,
    item_cls: type[BaseModel],
    threshold: int,
    values: list[dict] | None = None,
    *,
    from_instance: bool = False,
) -> list[str]:
    """Generate a root array of tables such as ``[[export]]``.

    The banner comes from the entry model and the description from the root
    field. The body is the entries in *values*. With none, a template shows
    one example entry and a config written from instances shows nothing.
    """
    field_info = get_root_config_provider().root_model().model_fields.get(section_name)
    title = (item_cls.__doc__ or section_name).strip().split("\n")[0]
    lines = ["", _RULE, f"# {title}", _RULE]
    if field_info is not None and field_info.description:
        lines.append("")
        append_comment_text(lines, field_info.description)
    lines.append("")
    lines.extend(
        _array_of_tables(
            _Ctx(threshold, from_instance=from_instance),
            section_name,
            field_info,
            item_cls,
            items=values if isinstance(values, list) else None,
            has_instance_value=False,
        )
    )
    return lines
