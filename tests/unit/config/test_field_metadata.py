"""Invariants for ``Field.json_schema_extra`` metadata across the codebase."""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from pydantic import BaseModel

from hydromodpy.core.config_kit.field_metadata import (
    field_metadata,
    is_valid_field_metadata,
    unknown_metadata_keys,
)


def test_field_metadata_helper_accepts_canonical_keys() -> None:
    payload = field_metadata(
        widget_type="slider",
        unit="m/s",
        display_min=0.0,
        display_max=1.0,
        display_name_fr="Conductivite",
        help_text_fr="Vitesse aquifere.",
        toml_exclude=False,
        group="advanced",
        stability="experimental",
    )
    assert is_valid_field_metadata(payload)


def test_field_metadata_helper_rejects_typos() -> None:
    with pytest.raises(ValueError, match="Unknown field_metadata keys"):
        field_metadata(widgettype="input")


_SKIP_MODULES = frozenset(
    {
        "hydromodpy.display.streamlit_config",
    }
)


def _iter_basemodel_classes():
    importlib.import_module("hydromodpy._bootstrap").bootstrap()
    package = importlib.import_module("hydromodpy")
    seen: set[type[BaseModel]] = set()
    for module_info in pkgutil.walk_packages(package.__path__, prefix="hydromodpy."):
        if module_info.name in _SKIP_MODULES:
            continue
        try:
            module = importlib.import_module(module_info.name)
        except BaseException:
            continue
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseModel)
                and attr is not BaseModel
                and attr not in seen
            ):
                seen.add(attr)
                yield attr


def test_no_unknown_keys_in_json_schema_extra_across_codebase() -> None:
    """All ``Field.json_schema_extra`` payloads use only canonical keys."""
    offenders: dict[str, set[str]] = {}
    for cls in _iter_basemodel_classes():
        for field_name, info in cls.model_fields.items():
            extra = info.json_schema_extra
            if not isinstance(extra, dict):
                continue
            unknown = unknown_metadata_keys(extra)
            if unknown:
                offenders[f"{cls.__module__}.{cls.__name__}.{field_name}"] = unknown

    assert not offenders, "Unknown json_schema_extra keys detected: " + ", ".join(
        f"{path}={sorted(keys)}" for path, keys in offenders.items()
    )
