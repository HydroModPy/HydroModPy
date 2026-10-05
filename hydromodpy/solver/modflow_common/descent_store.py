"""Hand the descent D the build saved to the run store, for both backends.

The build writes ``<model>.descent.npz`` in the solver folder. The extractors
do not see the model, so they find it there, as they find
``<model>.conditioning_ref.npy``, and write it under ``fields.zarr/mesh/``
right after the mesh. Figures and the accumulation of cell fluxes read it from
there. A run without the sidecar gets no D in its store: its readers rebuild
one from the stored top and say so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.mesh_descent import (
    DESCENT_SIDECAR_SUFFIX,
    read_descent_sidecar,
)

logger = get_logger(__name__)


def write_descent_sidecar_to_store(
    sz: Any,
    solver_output_dir: Path,
    *,
    sim_id: str,
    n_cells: int,
) -> bool:
    """Write the build's descent into ``sz``; return whether it was written.

    Never raises: the mesh is already stored and a bad sidecar must not cost
    it. A missing sidecar is an INFO line (an old scratch, a backend that
    builds no descent); a sidecar that is unreadable or does not match the
    mesh is a warning that names what reads the descent.
    """
    files = sorted(Path(solver_output_dir).glob(f"*{DESCENT_SIDECAR_SUFFIX}"))
    if not files:
        logger.info(
            "Run %s: no descent sidecar in %s, so no descent is stored. Readers rebuild one "
            "from the stored top, without channel pins, constant-head seeds or lakes.",
            sim_id,
            solver_output_dir,
        )
        return False
    try:
        record = read_descent_sidecar(files[0])
        if record is None:
            logger.info("Run %s: %s holds no descent; nothing stored.", sim_id, files[0].name)
            return False
        if int(record.receiver.size) != int(n_cells):
            raise ValueError(
                f"the descent holds {int(record.receiver.size)} cells, the mesh {int(n_cells)}."
            )
        sz.write_descent(
            receiver=record.receiver,
            surface=record.surface,
            base_level=record.base_level,
            constant_head=record.constant_head,
            raised=record.raised,
            channel=record.channel,
            pinned=record.pinned,
            dam_foot=record.dam_foot,
            attrs={
                "adjacency": str(record.adjacency),
                "epsilon": float(record.epsilon),
                **record.report(),
                "n_channel": int(record.n_channel),
                "n_pinned": int(record.n_pinned),
            },
        )
    except Exception:
        logger.warning(
            "Could not store the descent of run %s from %s; the flow direction map and the "
            "accumulation fluxes of this run rebuild one without channel pins.",
            sim_id,
            files[0].name,
            exc_info=True,
        )
        return False
    return True


__all__ = ("write_descent_sidecar_to_store",)
