"""Initial-condition resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.model.initial.heads import build_head_initial_condition_array

if TYPE_CHECKING:
    from hydromodpy.model.model import Model


class InitialConditionResolutionMixin:
    """Resolve the initial head field from the start state of the model."""

    mesh: object
    inputs: Model

    def resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the start state of the model into cell heads.

        A steady or cyclic start begins at the top, as on every backend. A state read
        from a run or a solve is refused by name, since Boussinesq reads no restart.
        """
        return build_head_initial_condition_array(
            self.inputs.initial,
            top=self.mesh.z_top_m,
            bottom=self.mesh.z_bottom_m,
            target_shape=(int(self.mesh.n_cells),),
            location_prefix="flow.ic",
        )


__all__ = ["InitialConditionResolutionMixin"]
