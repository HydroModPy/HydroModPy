"""Switch the river network on when the mesh follows the rivers."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import ConfigValidationError

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.mesh.config.mesh import MeshConfig

__all__ = ["prepare_geographic_config_for_mesh"]


def prepare_geographic_config_for_mesh(
    geographic_cfg: GeographicConfig,
    mesh_cfg: MeshConfig,
    *,
    active_bc: Collection[str],
) -> GeographicConfig:
    """Return *geographic_cfg* with ``[geographic.river_network]`` on when the mesh needs it.

    The rule is :meth:`MeshConfig.requires_river_trace`. A network that the
    mesh switches on still needs its threshold; without one this raises.
    """
    boundaries = {str(bc).strip().lower() for bc in active_bc}
    synthetic = geographic_cfg.uses_synthetic_geographic()
    if not mesh_cfg.requires_river_trace(active_bc=boundaries, synthetic=synthetic):
        return geographic_cfg
    network = geographic_cfg.river_network
    if network.enabled:
        return geographic_cfg
    reads_a_file = mesh_cfg.triangle is not None and mesh_cfg.triangle.path is not None
    if reads_a_file:
        needed_by = "The 'stream' boundary on the mesh read from [mesh.triangle] path"
    elif mesh_cfg.families.rivers == "cell":
        needed_by = f'mesh.engine = "{mesh_cfg.engine}" with [mesh.families] rivers = "cell"'
    else:
        needed_by = "[[mesh.refinement_zone]] where = 'height_above_stream'"
    refusal = network.missing_threshold_refusal(needed_by=needed_by)
    if refusal is not None:
        raise ConfigValidationError(refusal)
    return geographic_cfg.model_copy(
        update={"river_network": network.model_copy(update={"enabled": True})}, deep=True
    )
