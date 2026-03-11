"""Flow-family solver adapters.

The flow package is split by concrete backend:

- ``modflownwt`` builds the legacy MODFLOW-NWT solver instance,
- ``modflow6`` builds the MODFLOW 6 solver instance,
- ``common`` owns the shared execution lifecycle used by both.

This ``__init__`` file re-exports the concrete adapters expected by the
registry layer.
"""

from hydromodpy.simulation.adapters.flow.modflow6 import Modflow6FlowAdapter
from hydromodpy.simulation.adapters.flow.modflownwt import ModflowNwtFlowAdapter

__all__ = [
    "Modflow6FlowAdapter",
    "ModflowNwtFlowAdapter",
]
