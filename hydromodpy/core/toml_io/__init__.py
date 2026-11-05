"""TOML I/O and path-resolution helpers shared by every config layer.

Hosts the round-trip TOML loader/writer pair, the commented template
generator driven by Pydantic introspection, and the path-resolution
primitives used by config-aware modules. Import from the module that holds
the name: ``loader``, ``merge``, ``paths``, ``generator`` or ``writer``.

Layer rule: this sub-package may import only the standard library,
``tomllib`` / ``tomli_w`` / ``tomlkit`` / ``pydantic``, and
``hydromodpy.core.*``.
"""
