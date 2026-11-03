"""Typed errors raised by the generic schema migration runner."""

from __future__ import annotations

from hydromodpy.core.exceptions import MigrationFailedError


class MigrationError(MigrationFailedError):
    """Base class for every migration failure."""


class SchemaIntegrityError(MigrationError):
    """An already applied migration has a different checksum on disk."""


class MigrationDiscoveryError(MigrationError):
    """A versions directory contains gaps, duplicates or malformed names."""


class MigrationExecutionError(MigrationError):
    """A migration SQL script raised while executing against DuckDB."""
