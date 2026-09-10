"""Typed Zarr-store exceptions."""

from __future__ import annotations


class ZarrSchemaVersionError(RuntimeError):
    """Raised when an opened Zarr store advertises an unsupported schema."""

    def __init__(self, expected: str, actual: str | None) -> None:
        self.expected = expected
        self.actual = actual
        message = (
            f"Zarr schema version mismatch: expected {expected!r}, "
            f"found {actual!r}. There is no in-place upgrade for this store; "
            "rerun the simulation to regenerate it under the current schema."
        )
        super().__init__(message)
