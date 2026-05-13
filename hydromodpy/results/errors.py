"""Typed exceptions for the results / reader layer.

Inherit from :class:`hydromodpy.core.exceptions.CatalogError`. Multiple
inheritance with the historical stdlib parent (``KeyError`` /
``FileNotFoundError``) preserves backward-compatibility with callers that
caught the raw exception type. New code should catch the typed exception.
"""

from __future__ import annotations

from hydromodpy.core.exceptions import CatalogError


class FieldNotFoundError(CatalogError, KeyError):
    """A field name is registered but absent from the simulation store."""

    code = "HMPY.E821"


class RunNotFoundError(CatalogError, KeyError):
    """A ``sim_id`` does not exist in the catalog."""

    code = "HMPY.E822"


class ProjectNotFoundError(CatalogError, FileNotFoundError):
    """A project root or its ``hydromodpy.toml`` is missing."""

    code = "HMPY.E823"


class SchemaVersionMismatchError(CatalogError):
    """Stored schema version differs from ``CATALOG_SCHEMA_VERSION``."""

    code = "HMPY.E824"


__all__ = [
    "CatalogError",
    "FieldNotFoundError",
    "RunNotFoundError",
    "ProjectNotFoundError",
    "SchemaVersionMismatchError",
]
