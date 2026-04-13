"""Explicit algebraic formulations available in the Boussinesq solver."""

from hydromodpy.solver.boussinesq.formulations.common import (
    BoussinesqFormulationSpec,
)
from hydromodpy.solver.boussinesq.formulations.head_only_regularized_partition import (
    HEAD_ONLY_REGULARIZED_PARTITION,
)
from hydromodpy.solver.boussinesq.formulations.mixed_complementarity import (
    MIXED_COMPLEMENTARITY,
)

__all__ = [
    "BoussinesqFormulationSpec",
    "HEAD_ONLY_REGULARIZED_PARTITION",
    "MIXED_COMPLEMENTARITY",
]
