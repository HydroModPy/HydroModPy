"""Initial-condition resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions


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

        head_ic = initial_conditions.h
        ic_type = str(head_ic.type).strip().lower()
        if ic_type == "top":
            return np.asarray(self.mesh.z_top_m, dtype=float)
        if ic_type == "bottom":
            return np.asarray(self.mesh.z_bottom_m, dtype=float)
        if ic_type == "custom":
            if head_ic.value is None:
                raise ValueError("flow.ic.value is required when flow.ic.type='custom'.")
            head_magnitude = getattr(head_ic.value, "magnitude", head_ic.value)
            return np.full(self.mesh.n_cells, float(head_magnitude), dtype=float)
        raise ValueError(f"Unsupported flow.ic.type for boussinesq: '{head_ic.type}'.")


__all__ = ["InitialConditionResolutionMixin"]
