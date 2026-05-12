"""Typed errors raised by the catalog schema migration runner."""

from __future__ import annotations


class MigrationError(Exception):
    """Base class for every catalog migration failure."""


class SchemaIntegrityError(MigrationError):
    """An already applied migration has a different checksum on disk."""


class MigrationDiscoveryError(MigrationError):
    """A versions directory contains gaps, duplicates or malformed names."""


class MigrationExecutionError(MigrationError):
    """A migration SQL script raised while executing against DuckDB."""
