"""Leave the ground file beside a MODFLOW 6 model a test writes with flopy.

The extractor stores the ground the build left as ``<model>.ground.npz``, never
the DISV top, which is a computational top. A model written by hand has no
build, so its top is its ground.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.support.computational_top import GROUND_SIDECAR_SUFFIX


def leave_ground_beside(gwf) -> Path:
    """Write the top of ``gwf`` as its ground in the model folder; return the path."""
    path = Path(gwf.model_ws) / f"{gwf.name}{GROUND_SIDECAR_SUFFIX}"
    np.savez(path, ground=np.asarray(gwf.modelgrid.top, dtype=np.float64).reshape(-1))
    return path
