"""Method catalog for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.methods.catalog import (
    BoussinesqMethodSpec,
    HEAD_ONLY_REGULARIZED_PARTITION_METHOD,
    MIXED_COMPLEMENTARITY_METHOD,
    resolve_method_spec,
    resolve_surface_interaction_model_token,
)

__all__ = [
    "BoussinesqMethodSpec",
    "HEAD_ONLY_REGULARIZED_PARTITION_METHOD",
    "MIXED_COMPLEMENTARITY_METHOD",
    "resolve_method_spec",
    "resolve_surface_interaction_model_token",
]
