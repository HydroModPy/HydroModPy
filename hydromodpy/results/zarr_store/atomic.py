"""Atomic Zarr-array write helper with file-locking.

Provides :func:`atomic_write_array` to materialise a Zarr array via a
``tmp -> complete -> rename`` sequence so a partially written array is
never visible to readers.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import zarr

from hydromodpy.results.zarr_store.constants import BLOSC_ZSTD

STATUS_INCOMPLETE = "incomplete"
STATUS_COMPLETE = "complete"


def atomic_write_array(
    parent_dir: Path,
    name: str,
    data: np.ndarray,
    *,
    attrs: dict[str, Any] | None = None,
    compressors: Any = BLOSC_ZSTD,
) -> Path:
    """Atomically write a small Zarr array directory next to ``parent_dir``.

    Steps: open the local store under a ``<name>.zarr.tmp-<uuid>`` directory,
    set ``_status="incomplete"`` immediately, write data + user attrs, mark
    ``_status="complete"``, then ``os.replace`` the tmp directory to its
    final location. Any failure aborts the rename and removes the tmp dir.
    """
    parent_dir = Path(parent_dir)
    parent_dir.mkdir(parents=True, exist_ok=True)
    tmp_name = f"{name}.zarr.tmp-{uuid.uuid4().hex}"
    tmp_path = parent_dir / tmp_name
    final_path = parent_dir / name

    try:
        store = zarr.storage.LocalStore(str(tmp_path))
        root = zarr.open_group(store, mode="w")
        root.attrs["_status"] = STATUS_INCOMPLETE
        arr = root.create_array(
            "value",
            data=np.asarray(data),
            compressors=compressors,
            overwrite=True,
        )
        if attrs:
            arr.update_attributes(attrs)
        root.attrs["_status"] = STATUS_COMPLETE
        if hasattr(store, "close"):
            store.close()
    except BaseException:
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise

    if final_path.exists():
        shutil.rmtree(final_path)
    tmp_path.rename(final_path)
    return final_path


__all__ = ["atomic_write_array", "STATUS_INCOMPLETE", "STATUS_COMPLETE"]
