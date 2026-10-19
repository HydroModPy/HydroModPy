"""What a package installs into a workspace, and the one installer that places it.

An example, a published run and an exported project all carry the same
install index: every file with its destination, size and sha256, every row a
station registry needs, every site the package declares. The index is the
document ``INSTALL.toml`` (:mod:`hydromodpy.core.payload.index`); the
installer (:mod:`hydromodpy.core.payload.install`) plans every placement
before it writes one, so a conflict is named before anything changes.
"""

from __future__ import annotations

from hydromodpy.core.payload.index import (
    INSTALL_FILENAME,
    INSTALL_SCHEMA,
    InstallIndex,
    PayloadBundle,
    PayloadFile,
    PayloadStation,
    payload_file_of,
    read_index,
    render_index,
    sidecar_name,
    stored_name,
    write_index,
)
from hydromodpy.core.payload.install import (
    PayloadConflictError,
    Placement,
    StationMerge,
    destination,
    plan_files,
    plan_stations,
    refuse_conflicts,
    write_file,
    write_stations,
)

__all__ = [
    "INSTALL_FILENAME",
    "INSTALL_SCHEMA",
    "InstallIndex",
    "PayloadBundle",
    "PayloadConflictError",
    "PayloadFile",
    "PayloadStation",
    "Placement",
    "StationMerge",
    "destination",
    "payload_file_of",
    "plan_files",
    "plan_stations",
    "read_index",
    "refuse_conflicts",
    "render_index",
    "sidecar_name",
    "stored_name",
    "write_file",
    "write_index",
    "write_stations",
]
