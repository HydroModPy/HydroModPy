"""TOML I/O and path-resolution helpers shared by every config layer.

Hosts the round-trip TOML loader/writer pair, the commented template
generator driven by Pydantic introspection, and the path-resolution
primitives used by config-aware modules.

Layer rule: this sub-package may import only the standard library,
``tomllib`` / ``tomli_w`` / ``tomlkit`` / ``pydantic``, and
``hydromodpy.core.*``.
"""

from __future__ import annotations

from hydromodpy.core.toml_io.generator import (
    available_modules,
    generate_toml,
    generate_toml_from_instances,
)
from hydromodpy.core.toml_io.io import dump_toml_with_comments
from hydromodpy.core.toml_io.loader import (
    load_toml_with_base_config,
    merge_toml_payloads,
)
from hydromodpy.core.toml_io.paths import (
    get_nested_section,
    is_declared_absolute_path,
    resolve_declared_path,
    resolve_path,
)
from hydromodpy.core.toml_io.writer import dump, dumps

__all__ = [
    "available_modules",
    "dump",
    "dump_toml_with_comments",
    "dumps",
    "generate_toml",
    "generate_toml_from_instances",
    "get_nested_section",
    "is_declared_absolute_path",
    "load_toml_with_base_config",
    "merge_toml_payloads",
    "resolve_declared_path",
    "resolve_path",
]
