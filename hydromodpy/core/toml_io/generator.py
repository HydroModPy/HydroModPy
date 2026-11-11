"""Auto-generate commented TOML templates from Pydantic models.

Reads field names, types, defaults, descriptions, and Profile metadata
directly from Pydantic model_fields. Supports filtering by module and profile.

Supports ``list[BaseModel]`` fields, rendered as TOML array-of-tables
(``[[section.field]]``).

Usage::

    from hydromodpy.core.toml_io.generator import generate_toml

    print(
        generate_toml(modules=["geographic"], profile="user", root=HydroModPyConfig)
    )

    from hydromodpy.core.toml_io.generator import generate_toml_from_instances

    generate_toml_from_instances(
        {"hydrometry": cfg_h, "piezometry": cfg_p},
        output_path="config.toml",
        root=HydroModPyConfig,
    )

The caller passes the root class and, when it wants the dynamic example blocks, a
``flow_examples`` function that the layer owning the section provides. The shapes of the
models are read through ``model_types.py``, one table is written by ``section.py``, and
``render.py`` formats keys, values and comments.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from collections.abc import Mapping as _abc_Mapping
from pathlib import Path

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import (
    extract_profile,
    resolve_profile,
)
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.registry import (
    repeated_root_sections,
    root_scalar_fields,
    root_sections,
)
from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.toml_io.model_types import restore_variant_tags
from hydromodpy.core.toml_io.render import (
    UNDEFINED,
    default_value,
    fmt,
    placeholder,
    render_field_comment,
)
from hydromodpy.core.toml_io.section import repeated_root_section, section


def available_modules(root: type[BaseModel] | RootConfig) -> list[str]:
    """Return the list of registered config module names."""
    return list(root_sections(root).keys())


def generate_toml(
    output_path: str | Path | None = None,
    modules: list[str] | None = None,
    profile: str = "expert",
    overrides: dict[str, dict] | None = None,
    *,
    root: type[BaseModel] | RootConfig,
    flow_examples: Callable[[int, Callable[..., list[str]]], list[str]] | None = None,
) -> str:
    """Generate a commented TOML template filtered by modules and profile.

    Parameters
    ----------
    output_path : str, Path, or None
        If provided, write the template to this file.
    modules : list of str, or None
        Module sections to include (e.g. ["geographic", "modflow_nwt"]).
        None = all registered modules.
    profile : str
        Visibility profile: "user", "dev", or "expert".
        Only fields with Profile <= profile are included.
    overrides : dict of {section_name: {field_name: value}}, or None
        Concrete values to write instead of model defaults.
        Fields present in overrides with a non-None value are written
        uncommented; fields set to None follow the default commented-out
        behavior for optional fields.
    root : model class or RootConfig
        The root configuration the template enumerates the sections of.
    flow_examples : callable or None
        ``(threshold, section_renderer) -> lines`` that renders the example
        blocks of the dynamic ``[flow.*]`` tables. Without it, the template
        has no such block.

    Returns
    -------
    str
        The TOML content.
    """
    threshold = resolve_profile(profile)

    registry = root_sections(root)

    if modules is None:
        selected = dict(registry)
    else:
        unknown = set(modules) - set(registry)
        if unknown:
            raise ValueError(
                f"Unknown module(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(registry))}"
            )
        selected = {k: registry[k] for k in modules}

    scalar_fields = root_scalar_fields(root)
    selected_root_names = [
        name
        for name, field_info in scalar_fields.items()
        if extract_profile(field_info) <= threshold
    ]

    lines = _header(profile, [*selected_root_names, *list(selected.keys())])
    lines.extend(_root_scalars(scalar_fields, threshold))

    repeated = repeated_root_sections(root)
    for section_name, model_cls in selected.items():
        section_values = (overrides or {}).get(section_name)
        if section_name in repeated:
            lines.extend(
                repeated_root_section(
                    section_name, model_cls, threshold, values=section_values, root=root
                )
            )
            continue
        lines.extend(section(section_name, model_cls, threshold, values=section_values))
        if section_name == "flow" and flow_examples is not None:
            lines.extend(flow_examples(threshold, section))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


def generate_toml_from_instances(
    instances: _abc_Mapping[str, BaseModel | list[BaseModel]],
    output_path: str | Path | None = None,
    profile: str = "user",
    *,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    comment: str | None = None,
    root: type[BaseModel] | RootConfig,
) -> str:
    """Generate a fully-filled TOML from instantiated Pydantic models.

    Works with **any** Pydantic model -- not limited to registered modules.
    Supports ``list[BaseModel]`` fields (rendered as ``[[section.sources]]``).
    A list of models is a repeated root section: one ``[[name]]`` block per
    entry, as ``[[export]]`` is written.

    When *output_path* is given, ``Path`` values are automatically
    relativised to the output directory.

    Parameters
    ----------
    instances : dict of {section_name: model_instance or list of them}
        E.g. ``{"hydrometry": cfg_h, "export": cfg.export}``.
    output_path : str, Path, or None
        If provided, write the result to this file.
    profile : str
        Visibility profile controlling which fields are included.
    exclude_defaults : bool
        Omit fields that equal their default value (cleaner output).
    exclude_none : bool
        Omit fields whose value is ``None``.
    comment : str or None
        Optional header comment (may be multi-line).
    root : model class or RootConfig
        The root configuration a repeated section reads its field description
        from.

    Returns
    -------
    str
        The TOML content.

    Example
    -------
    ::

        from hydromodpy.core.toml_io.generator import generate_toml_from_instances

        generate_toml_from_instances(
            {"hydrometry": cfg_h, "piezometry": cfg_p},
            output_path="config.toml",
            exclude_defaults=True,
            exclude_none=True,
            comment="My project config",
        )
    """
    threshold = resolve_profile(profile)
    toml_dir = Path(output_path).resolve().parent if output_path else None

    lines = _instances_banner(profile, instances, comment)
    for section_name, model in instances.items():
        if isinstance(model, list):
            if model:
                entries = [
                    _dump_instance(entry, exclude_defaults, exclude_none, toml_dir)
                    for entry in model
                ]
                lines.extend(
                    repeated_root_section(
                        section_name,
                        type(model[0]),
                        threshold,
                        entries,
                        from_instance=True,
                        root=root,
                    )
                )
            continue
        values = _dump_instance(model, exclude_defaults, exclude_none, toml_dir)
        lines.extend(
            section(section_name, type(model), threshold, values=values, from_instance=True)
        )

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


# =====================================================================
# Internal helpers
# =====================================================================


def _instances_banner(
    profile: str, instances: _abc_Mapping[str, object], comment: str | None
) -> list[str]:
    """Return the top of a config written from instances: *comment*, or the header."""
    if not comment:
        return _header(profile, list(instances.keys()))
    rule = "# " + "=" * 70
    return [
        rule,
        *(f"# {cline}" for cline in comment.split("\n")),
        rule,
        "# Generated from Pydantic config export.",
        "",
    ]


def _dump_instance(
    model: BaseModel,
    exclude_defaults: bool,
    exclude_none: bool,
    toml_dir: Path | None,
) -> dict:
    """Dump *model* to a dict, tags restored, paths relative to *toml_dir* if given."""
    values = model.model_dump(exclude_defaults=exclude_defaults, exclude_none=exclude_none)
    restore_variant_tags(model, values)
    if toml_dir:
        _relativize_paths_in_dict(values, toml_dir)
    return values


def _relativize_paths_in_dict(d: dict, toml_dir: Path) -> None:
    """In-place: convert absolute Path/str paths to relative strings."""
    for key, val in d.items():
        if isinstance(val, Path):
            d[key] = os.path.relpath(str(val), str(toml_dir)) if val.is_absolute() else str(val)
        elif isinstance(val, str) and os.path.isabs(val):
            d[key] = os.path.relpath(val, str(toml_dir))
        elif isinstance(val, dict):
            _relativize_paths_in_dict(val, toml_dir)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _relativize_paths_in_dict(item, toml_dir)


def _header(profile: str, modules: list[str]) -> list[str]:
    return [
        "# " + "=" * 70,
        "# HydroModPy Configuration",
        f"# Profile: {profile} | Modules: {', '.join(modules)}",
        "# Auto-generated from Pydantic models.",
        "# Edit values below. Comments describe each parameter.",
        "# " + "=" * 70,
        "",
    ]


# --------------------------------------------------------------------------
# Header and root scalars
# --------------------------------------------------------------------------


def _root_scalars(
    fields: dict[str, FieldInfo],
    threshold: int,
) -> list[str]:
    """Generate root-level scalar TOML fields such as ``workflow``."""
    selected = [
        (name, field_info, extract_profile(field_info))
        for name, field_info in fields.items()
        if extract_profile(field_info) <= Profile(threshold)
    ]
    if not selected:
        return []

    lines = [
        "",
        "# " + "-" * 70,
        "# Root-level workflow selector.",
        "# " + "-" * 70,
        "",
    ]
    for name, field_info, level in selected:
        render_field_comment(lines, field_info)
        default = default_value(field_info)
        if default is not UNDEFINED and default is not None:
            lines.append(f"{name} = {fmt(default)}")
        elif level == Profile.USER and default is UNDEFINED:
            lines.append(f"{name} = {placeholder(field_info)}")
        else:
            lines.append(f"# {name} = {placeholder(field_info)}")
    return lines
