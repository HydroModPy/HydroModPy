"""Initial-condition resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.initial_conditions import build_head_initial_condition_array


class InitialConditionResolutionMixin:
    """Resolve the initial head field from the HydroModPy flow contract."""

    mesh: object
    flow: object

    def resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the canonical `Flow` initial condition into cell heads."""
        initial_conditions = getattr(self.flow, "initial_conditions", None)
        if not isinstance(initial_conditions, FlowInitialConditions):
            raise TypeError(
                "Boussinesq expects flow.initial_conditions to be one "
                "FlowInitialConditions instance."
            )

        return build_head_initial_condition_array(
            initial_conditions.h,
            top=self.mesh.z_top_m,
            bottom=self.mesh.z_bottom_m,
            target_shape=(int(self.mesh.n_cells),),
            location_prefix="flow.ic",
        )


__all__ = ["InitialConditionResolutionMixin"]
