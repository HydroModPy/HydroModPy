"""Persistence steps - write mesh, flow parameters and geographic rasters."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import MeshError

if TYPE_CHECKING:
    from hydromodpy.physics.flow import Flow
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_persist_params(
    store,
    sim_id: str,
    flow: Flow,
    *,
    domain: Domain | None = None,
) -> None:
    """Write hydraulic parameters from a Flow object into the catalog.

    Also persists the domain aquifer thickness (from domain.depth_model) as a
    global scalar, since it is a calibratable quantity listed alongside K/Sy/Ss.
    """
    params: list[dict] = []

    params_dict = getattr(flow, "parameters", None)
    if params_dict:
        for pid, fp in params_dict.items():
            kind = getattr(fp, "kind", "homogeneous")
            if kind == "homogeneous":
                params.append(
                    {
                        "param_name": pid,
                        "zone_id": None,
                        "value": getattr(fp, "value", None),
                        "unit": getattr(fp, "unit", ""),
                        "parameterization": "homogeneous",
                    }
                )
            else:
                values_by_key = getattr(fp, "values_by_key", None) or {}
                for zone_key, val in values_by_key.items():
                    params.append(
                        {
                            "param_name": pid,
                            "zone_id": str(zone_key),
                            "value": val,
                            "unit": getattr(fp, "unit", ""),
                            "parameterization": "geology_mapped",
                        }
                    )

    if domain is not None:
        depth_model = getattr(domain, "depth_model", None)
        thickness = getattr(depth_model, "thickness", None) if depth_model else None
        if thickness is not None:
            params.append(
                {
                    "param_name": "thickness",
                    "zone_id": None,
                    "value": float(thickness),
                    "unit": "m",
                    "parameterization": "homogeneous",
                }
            )

    if params:
        store.write_parameters(sim_id, params)


def step_persist_mesh(ctx: WorkflowContext, sim_id: str) -> None:
    """Write mesh topology into the simulation's Zarr.

    The mesh is always materialised as a :class:`HydroMesh`: an explicit
    Gmsh planar mesh when one is loaded, or a structured-from-DEM mesh
    derived from ``domain.surface_topo.support`` otherwise. Lumped
    simulations (no Domain attached, e.g. GR4J) are skipped: there is no
    spatial discretisation to persist.

    Layer interfaces come from ``Domain.z_interfaces``, derived from the
    topographic surface and the configured depth model.
    """
    import numpy as np

    domain = ctx.setup.domain
    if domain is None:
        return

    z_intf = np.asarray(domain.z_interfaces, dtype=float)

    mesh_planar = ctx.setup.mesh_planar
    if mesh_planar is not None:
        vertices = mesh_planar.points_xy
        connectivity = mesh_planar.connectivity
    else:
        from hydromodpy.spatial.mesh.grid_wrappers import RegularGrid

        support = getattr(domain.surface_topo, "support", None)
        if support is None or support.nrows is None or support.ncols is None:
            raise MeshError(
                "step_persist_mesh: no Gmsh planar mesh and no raster support "
                "on domain.surface_topo - cannot materialise a HydroMesh"
            )
        regular = RegularGrid(
            shape=(int(support.nrows), int(support.ncols)),
            dx=float(support.dx),
            dy=float(support.dy),
            origin=(float(support.xmin), float(support.ymax)),
            n_layers=max(int(z_intf.size) - 1, 1),
            crs=str(support.crs) if support.crs is not None else None,
        )
        hydro_mesh = regular.to_hydro_mesh()
        vertices = hydro_mesh.vertices
        connectivity = hydro_mesh.flat_connectivity

    ctx.store.write_mesh(
        sim_id,
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=z_intf,
    )


def step_persist_geographic(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist the geographic rasters (DEM, watershed masks) into the Zarr."""
    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is None:
        return
    persist_geographic_to_store(ctx.setup.geographic, ctx.store, sim_id=sim_id)
