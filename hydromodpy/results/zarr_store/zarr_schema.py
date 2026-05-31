"""Schema concerns for :class:`SimulationZarr`.

Owns the on-disk layout contract: ZARR_SCHEMA_VERSION enforcement,
``_SUBGROUPS`` materialisation on init, and the strict root-open helper
that validates the schema version on every reopen.

Pure functions; no instance state is held here.
"""

from __future__ import annotations

import asyncio
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import zarr
from upath import UPath

from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results.storage_contract import ZARR_ZIP_SUFFIX
from hydromodpy.results.zarr_store.constants import (
    _SUBGROUPS,
    CF_CONVENTIONS,
    ZARR_SCHEMA_VERSION,
)
from hydromodpy.results.zarr_store.exceptions import ZarrSchemaVersionError

LOCAL_STORE_WRITE_RETRIES = 5
LOCAL_STORE_WRITE_RETRY_BASE_DELAY_SECONDS = 0.05


def _is_retryable_local_store_write_error(exc: BaseException) -> bool:
    """Return True for transient local-store write failures worth retrying."""
    return isinstance(exc, PermissionError)


class RetryingLocalStore(zarr.storage.LocalStore):
    """Local Zarr store with short retries for transient Windows file locks."""

    async def set(self, key: str, value: Any) -> None:
        for attempt in range(LOCAL_STORE_WRITE_RETRIES):
            try:
                return await super().set(key, value)
            except Exception as exc:
                if (
                    not _is_retryable_local_store_write_error(exc)
                    or attempt == LOCAL_STORE_WRITE_RETRIES - 1
                ):
                    raise
                await asyncio.sleep(LOCAL_STORE_WRITE_RETRY_BASE_DELAY_SECONDS * (attempt + 1))

    async def set_if_not_exists(self, key: str, value: Any) -> None:
        for attempt in range(LOCAL_STORE_WRITE_RETRIES):
            try:
                return await super().set_if_not_exists(key, value)
            except FileExistsError:
                return None
            except Exception as exc:
                if (
                    not _is_retryable_local_store_write_error(exc)
                    or attempt == LOCAL_STORE_WRITE_RETRIES - 1
                ):
                    raise
                await asyncio.sleep(LOCAL_STORE_WRITE_RETRY_BASE_DELAY_SECONDS * (attempt + 1))


def is_zip_store_path(path: Path) -> bool:
    """Return True for paths that resolve to a packed ``.zarr.zip`` archive."""
    return path.suffix == ".zip" or str(path).endswith(ZARR_ZIP_SUFFIX)


def windows_long_path(path: Path) -> Path:
    """Return a Windows extended-length path when needed by local stores."""
    if os.name != "nt":
        return path
    text = str(path.resolve())
    if text.startswith("\\\\?\\"):
        return Path(text)
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text.lstrip("\\"))
    return Path("\\\\?\\" + text)


def local_store_path_arg(path: Path) -> str:
    """Format a local-store path argument for :class:`zarr.storage.LocalStore`."""
    return str(windows_long_path(path)) if os.name == "nt" else str(path)


def local_store(path: Path, *, read_only: bool = False) -> RetryingLocalStore:
    """Return the HydroModPy local Zarr store implementation for ``path``."""
    return RetryingLocalStore(local_store_path_arg(path), read_only=read_only)


def ensure_local_zarr_node_dir(store_path: Path, zarr_path: str | None = None) -> None:
    """Pre-create a directory node under a local Zarr store (no-op for zip)."""
    if is_zip_store_path(store_path):
        return
    if zarr_path:
        target = store_path.joinpath(*zarr_path.split("/"))
    else:
        target = store_path
    windows_long_path(target).mkdir(parents=True, exist_ok=True)


def child_zarr_path(target: zarr.Group, name: str) -> str:
    """Concatenate the Zarr-internal path of ``target`` with ``name``."""
    base = target.path or ""
    return f"{base}/{name}" if base else name


def update_attrs(node: Any, attrs: dict[str, object]) -> Any:
    """Apply one merged metadata write to a Zarr group/array."""
    if not attrs:
        return node
    return node.update_attributes(attrs)


def open_root_strict(store: Any, *, read_only: bool) -> zarr.Group:
    """Open the root group of ``store`` and validate the schema version.

    The v2 contract requires every persisted store to carry a non-null
    ``zarr_schema_version`` attribute matching ``ZARR_SCHEMA_VERSION`` at
    the root. Mismatch, absence and null all raise
    :class:`ZarrSchemaVersionError`. A freshly created empty directory is
    the only exempted case (``__init__`` racing with ``create``).
    """
    mode = "r" if read_only else "a"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                "Consolidated metadata is currently not part .* Zarr format 3 specification.*"
            ),
            category=UserWarning,
        )
        try:
            root = zarr.open_group(store, mode=mode, use_consolidated=True)
        except (KeyError, ValueError):
            root = zarr.open_group(store, mode=mode)
    is_empty = not dict(root.attrs) and not list(root.keys())
    if is_empty and not read_only:
        return root
    actual = root.attrs.get("zarr_schema_version")
    if actual is None or str(actual) != ZARR_SCHEMA_VERSION:
        raise ZarrSchemaVersionError(
            ZARR_SCHEMA_VERSION,
            None if actual is None else str(actual),
        )
    return root


def initialise_root(
    path: Path | UPath | str,
    *,
    n_cells: int,
    n_layers: int,
    cell_types: list[str] | None,
    geographic_fingerprint: str | None,
) -> tuple[Path, Any, zarr.Group]:
    """Create the on-disk store with the v2 layout and return its handles.

    Materialises the root group with the mandatory ``Conventions`` /
    ``zarr_schema_version`` / ``created_at`` attributes, then creates the
    seven canonical subgroups (``meta``, ``mesh``, ``state``, ``derived``,
    ``budget``, ``particles``, ``forcing``).
    """
    path = Path(str(path))
    ensure_local_zarr_node_dir(path)
    store = local_store(path)
    root = zarr.open_group(store, mode="w")
    root_attrs: dict[str, object] = {
        "Conventions": CF_CONVENTIONS,
        "hydromodpy_version": _HMP_VERSION,
        "zarr_schema_version": ZARR_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "n_cells": int(n_cells),
        "n_layers": int(n_layers),
        "chunking": "balanced",
    }
    if cell_types is not None:
        root_attrs["cell_types"] = list(cell_types)
    if geographic_fingerprint is not None:
        root_attrs["geographic_fingerprint"] = str(geographic_fingerprint)
    root = update_attrs(root, root_attrs)

    for sub in _SUBGROUPS:
        ensure_local_zarr_node_dir(path, sub)
        root.create_group(sub)

    meta = root["meta"]
    update_attrs(meta, {"zarr_schema_version": ZARR_SCHEMA_VERSION})
    return path, store, root


__all__ = [
    "LOCAL_STORE_WRITE_RETRIES",
    "RetryingLocalStore",
    "child_zarr_path",
    "ensure_local_zarr_node_dir",
    "initialise_root",
    "is_zip_store_path",
    "local_store",
    "local_store_path_arg",
    "open_root_strict",
    "update_attrs",
    "windows_long_path",
]
