"""The mesh planner: from ``[mesh]`` and the project inputs to one mesh request.

One entry point, :func:`plan_mesh_request`. The other modules read what the
mesh step gathers: the geology contacts, a triangulation from a ``.msh``
file, the refinement zones, and the river-network switch of the geographic
configuration.
"""

from __future__ import annotations

from hydromodpy.spatial.mesh.planning.geographic import prepare_geographic_config_for_mesh
from hydromodpy.spatial.mesh.planning.geology import GeologyLines, contact_lines, geology_lines
from hydromodpy.spatial.mesh.planning.input_mesh import domain_polygon_of, read_input_triangulation
from hydromodpy.spatial.mesh.planning.inputs import LakeStructure, PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.planning.refinement import RefinementZone, load_refinement_zones
from hydromodpy.spatial.mesh.planning.resample import ResampledFamilies, resample_families

__all__ = [
    "GeologyLines",
    "LakeStructure",
    "PlanningInputs",
    "RefinementZone",
    "ResampledFamilies",
    "contact_lines",
    "domain_polygon_of",
    "geology_lines",
    "load_refinement_zones",
    "plan_mesh_request",
    "prepare_geographic_config_for_mesh",
    "read_input_triangulation",
    "resample_families",
]
