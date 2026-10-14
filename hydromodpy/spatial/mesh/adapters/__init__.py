"""Public adapter entry points around ``HydroMesh``.

This subpackage groups the conversions that are meant to be imported from the
outside world:

- ``meshio`` round-trips for file-oriented workflows,
- the ``flopy`` bridge to MODFLOW 6 DISV arguments,
- adapters from internal field and Gmsh mesh objects.

The functions re-exported here are intentionally small and concrete so that a
caller can usually guess which one to use from the source object it already
has in hand.
"""

from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import (
    from_field_mesh,
    from_gmsh_planar,
)
from hydromodpy.spatial.mesh.adapters.flopy_adapter import (
    to_flopy_disv_args,
)
from hydromodpy.spatial.mesh.adapters.meshio_adapter import (
    from_meshio,
    to_meshio,
)

__all__ = (
    "from_meshio",
    "to_meshio",
    "from_field_mesh",
    "from_gmsh_planar",
    "to_flopy_disv_args",
)
