"""Typed exceptions for the results / reader layer.

Inherit from :class:`hydromodpy.core.exceptions.CatalogError`. Multiple
inheritance with the stdlib parent (``KeyError`` / ``FileNotFoundError``)
keeps the raw exception type catchable. A class that is a
``FileNotFoundError`` says its category, ``not_found``, on itself.
"""

from __future__ import annotations

from hydromodpy.core.exceptions import CatalogError, Category


class FieldNotFoundError(CatalogError, KeyError):
    """A field name is registered but absent from the simulation store."""

    code = "HMPY.E821"


class RunNotFoundError(CatalogError, KeyError):
    """A ``sim_id`` does not exist in the catalog."""

    code = "HMPY.E822"


class ProjectNotFoundError(CatalogError, FileNotFoundError):
    """A project root or its ``project.toml`` is missing."""

    code = "HMPY.E823"
    category = Category.NOT_FOUND


class RunNotSealedError(CatalogError, FileNotFoundError):
    """A run has no ``manifest.json``: it never completed, so it has no seal to read."""

    code = "HMPY.E825"
    category = Category.NOT_FOUND


class SeveralCasesError(CatalogError):
    """A session of several cases was asked for the one run or the one case it does not have."""


__all__ = [
    "SeveralCasesError",
    "FieldNotFoundError",
    "RunNotFoundError",
    "ProjectNotFoundError",
    "RunNotSealedError",
]
