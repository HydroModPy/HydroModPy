"""What role each constant-head cell plays, written beside the deck.

MODFLOW 6 places the ocean, the stream and the lateral boundaries in a single
CHD package, so the budget holds one CHD term for the three of them. Which
cells carry the stream role is a fact of the build, not of the deck: a stream
cell and a lateral cell can be the same cell, and the row that survives the
merge is the last one written. The mask the builder used is therefore the only
thing that tells a stream CHD apart from an ocean or a side CHD, and nothing in
the deck, the budget file or the head file records it.

The builder writes it next to the solver files, on the pattern the LAK obs
sidecar already follows, so post-run extraction reads the roles from the run
directory and needs no live flopy object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.core.exceptions import SolverInputError

CONSTANT_HEAD_ROLES_SUFFIX = ".chd_roles.json"

#: Roles the MF6 build can place in the single CHD package, in merge order.
CONSTANT_HEAD_ROLES: tuple[str, ...] = ("ocean", "stream")


@dataclass(frozen=True)
class ConstantHeadRoles:
    """Cells the build assigned to each constant-head role, one flat index set."""

    n_cells: int
    cells_by_role: dict[str, np.ndarray]

    def mask_for(self, role: str) -> np.ndarray:
        """Flat ``(n_cells,)`` boolean mask of the cells carrying ``role``."""
        mask = np.zeros(int(self.n_cells), dtype=bool)
        cells = self.cells_by_role.get(role)
        if cells is not None and cells.size:
            mask[cells] = True
        return mask

    def has_role(self, role: str) -> bool:
        """True when at least one cell carries ``role`` on this run."""
        cells = self.cells_by_role.get(role)
        return cells is not None and bool(cells.size)


def roles_path(directory: Path | str, model_output_name: str) -> Path:
    """Path of the role sidecar for one model inside its solver directory."""
    return Path(directory) / f"{model_output_name}{CONSTANT_HEAD_ROLES_SUFFIX}"


def write_constant_head_roles(
    directory: Path | str,
    model_output_name: str,
    *,
    n_cells: int,
    masks_by_role: dict[str, np.ndarray],
) -> Path:
    """Persist the role of every constant-head cell beside the solver files.

    A role with no cell is written as an empty list rather than omitted, so a
    reader tells "this run built no ocean boundary" apart from "this run was
    written by a build that did not know about the ocean role".
    """
    unknown = sorted(set(masks_by_role) - set(CONSTANT_HEAD_ROLES))
    if unknown:
        raise SolverInputError(
            f"Constant-head roles {unknown} are not part of the declared roles "
            f"{list(CONSTANT_HEAD_ROLES)}."
        )
    payload = {
        "n_cells": int(n_cells),
        "cells_by_role": {
            role: [
                int(cell) for cell in np.flatnonzero(_flat_mask(masks_by_role.get(role), n_cells))
            ]
            for role in CONSTANT_HEAD_ROLES
        },
    }
    path = roles_path(directory, model_output_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    return path


def read_constant_head_roles(
    directory: Path | str, model_output_name: str
) -> ConstantHeadRoles | None:
    """Read the role sidecar of one model, or None when the run wrote none.

    A missing sidecar is the normal answer for a backend that builds no CHD
    package and for a run produced before the sidecar existed. The caller then
    knows nothing about the roles, which is what it knew before.
    """
    path = roles_path(directory, model_output_name)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    n_cells = int(payload["n_cells"])
    cells_by_role = {
        str(role): np.asarray(cells, dtype=int).reshape(-1)
        for role, cells in dict(payload.get("cells_by_role", {})).items()
    }
    return ConstantHeadRoles(n_cells=n_cells, cells_by_role=cells_by_role)


def _flat_mask(mask: np.ndarray | None, n_cells: int) -> np.ndarray:
    """Coerce one role mask to a flat ``(n_cells,)`` boolean array."""
    if mask is None:
        return np.zeros(int(n_cells), dtype=bool)
    flat = np.asarray(mask, dtype=bool).reshape(-1)
    if flat.size != int(n_cells):
        raise SolverInputError(
            f"A constant-head role mask covers {flat.size} cells and the grid has {n_cells}."
        )
    return flat


__all__ = (
    "CONSTANT_HEAD_ROLES",
    "CONSTANT_HEAD_ROLES_SUFFIX",
    "ConstantHeadRoles",
    "read_constant_head_roles",
    "roles_path",
    "write_constant_head_roles",
)
