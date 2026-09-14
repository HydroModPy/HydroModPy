"""Recharge map per cell."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


@register
class RechargeMap(ScalarFaceMap):
    """Per-cell recharge flux at a single timestep.

    Reads the canonical ``recharge`` budget field, which both MODFLOW
    backends write under the same name (MODFLOW 6 ``RCHA`` and MODFLOW-NWT
    ``RECHARGE`` are normalized at extraction).
    """

    spec = FigureSpec(
        name="recharge_map",
        title="Recharge",
        kind="spatial",
        required_fields=("recharge",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap = "YlGnBu"
    default_overlays = ("watershed",)

    def title(self, sim: Run, *, timestep: int) -> str:
        """Annotate the mean value when the field is spatially uniform.

        A uniform recharge otherwise renders as a flat colour with a
        cosmetic colorbar spanning floating-point noise.
        """
        base = super().title(sim, timestep=timestep)
        values = self.values(sim, timestep=timestep, layer=None)
        finite = np.asarray(values, dtype="float64")
        finite = finite[np.isfinite(finite)]
        if finite.size and np.allclose(finite, finite[0], rtol=1e-9):
            base += f"  -  uniform, {finite[0]:.3g} {self.field_descriptor_for('recharge').units}"
        return base
