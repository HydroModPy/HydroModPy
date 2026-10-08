"""Guard against opaque payloads in the root configuration schema.

The parameter reference is read from the Pydantic ``model_fields``. A
``dict[str, object]`` under ``HydroModPyConfig`` hides a structure the
reference cannot show, unless its path is a free-form mapping listed in
``INTENTIONALLY_OPAQUE_PATHS``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from hydromodpy.config import HydroModPyConfig

_OPAQUE_DICT_VALUE = re.compile(
    r"\bdict\[\s*str\s*,\s*(object|dict\[str,\s*object\])",
    re.IGNORECASE,
)

# Mappings from an external key (geology zone, station id) to a scalar value.
INTENTIONALLY_OPAQUE_PATHS = frozenset(
    {
        "mesh_catchment.hydraulic_properties.conductivity.values",
        "mesh_catchment.hydraulic_properties.storage_coefficient.values",
    }
)


def _annotation_text(annotation: object) -> str:
    return annotation.__name__ if isinstance(annotation, type) else str(annotation)


def _opaque_fields(model: type[BaseModel], section_path: str, seen: set[int]) -> list[str]:
    paths: list[str] = []
    for name, field in model.model_fields.items():
        if field.exclude:
            continue
        path = f"{section_path}.{name}" if section_path else name
        if _OPAQUE_DICT_VALUE.search(_annotation_text(field.annotation)):
            paths.append(path)
        for arg in (field.annotation, *getattr(field.annotation, "__args__", ())):
            if isinstance(arg, type) and issubclass(arg, BaseModel) and id(arg) not in seen:
                paths.extend(_opaque_fields(arg, path, seen | {id(arg)}))
    return paths


def test_no_opaque_dicts_in_root_schema() -> None:
    opaque = _opaque_fields(HydroModPyConfig, "", {id(HydroModPyConfig)})
    assert set(opaque) - INTENTIONALLY_OPAQUE_PATHS == set()
