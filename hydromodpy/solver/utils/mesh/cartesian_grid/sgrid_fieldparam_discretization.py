"""Core discretization primitives for planar-to-3D extrusion of FieldParam on one SGrid.

Design note
-----------
The mesh adapter used here is intentionally planar (2D XY support), and the
3D result is produced by extrusion:
- geology support is currently raster-based and discretized on 2D cells,
- values are then evaluated on all SGrid layers using layer-center depths.

As a result:
- `values_3d` is the main solver-ready output,
- `values_2d` is kept as a legacy compatibility artifact for existing
  plan-view examples.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.field.cases.square.field_mesh_square import StructuredFieldMesh
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter import (
    build_field_mesh_from_sgrid,
)


@dataclass(frozen=True)
class SGridFieldParamDiscretizationResult:
    """Result bundle for one discretization run.

    values_3d:
        Final 3D array (nlay, nrow, ncol) aligned with the full SGrid.
    values_2d:
        Legacy planar array (nrow, ncol), kept for backward compatibility and
        planar visualizations in examples.
    mesh:
        Intermediate field mesh used for geology projection.
    field_discretization:
        Output of ``geology_field.on_mesh(...)`` (zone fractions).
    """

    values_3d: np.ndarray
    values_2d: np.ndarray
    mesh: StructuredFieldMesh
    field_discretization: object


def _compute_layer_center_depths(sgrid) -> np.ndarray:
    """Return positive-downward depth at each layer center.

    The depth reference is the local model top (depth=0 at surface):
    ``depth = top - 0.5 * (ztop_layer + zbot_layer)``.
    """
    top = np.asarray(getattr(sgrid, "top"), dtype=float)
    botm = np.asarray(getattr(sgrid, "botm"), dtype=float)
    if botm.ndim != 3:
        raise ValueError("sgrid.botm must be a 3D array shaped as (nlay, nrow, ncol)")

    nlay, nrow, ncol = botm.shape
    if top.shape != (nrow, ncol):
        raise ValueError(
            "sgrid.top shape mismatch with sgrid.botm: "
            f"top{top.shape} vs botm{botm.shape}"
        )

    ztop = np.empty_like(botm, dtype=float)
    ztop[0, :, :] = top
    if nlay > 1:
        ztop[1:, :, :] = botm[:-1, :, :]
    zmid = 0.5 * (ztop + botm)
    return np.maximum(0.0, top[None, :, :] - zmid)


def discretize_fieldparam_on_sgrid(
    *,
    geology_field,
    field_param,
    sgrid,
    cell_samples_per_axis: int | None = None,
    depth: float = 0.0,
    strict_field_spatial_id_match: bool = True,
) -> SGridFieldParamDiscretizationResult:
    """Discretize one ``FieldParam`` on one structured solver grid.

    Why this function is central
    ----------------------------
    This is the core bridge between:
    - a spatial support (``geology_field``),
    - a parameter definition (``field_param``),
    - and the solver grid layout (``sgrid``).

    The function performs two different operations that are often confused:
    1) *Geometry projection*: estimate geology-zone fractions inside each cell.
    2) *Value mapping*: convert those fractions into numeric parameter values.

    Step-by-step workflow
    ---------------------
    1) Validate minimal runtime contracts on input objects.
    2) Convert the solver ``sgrid`` to a generic field mesh.
    3) Project geology on this mesh with sub-sampling.
    4) Ask ``field_param`` to compute planar values per mesh cell.
    5) Evaluate those values over all SGrid layers (full 3D).
    6) Keep a legacy 2D planar output for existing map-based workflows.

    Parameters
    ----------
    geology_field:
        Object exposing ``identifier`` and ``on_mesh(mesh, ...)``.
    field_param:
        Object exposing ``to_mesh_field(...)`` and optional heterogeneous metadata.
    sgrid:
        FloPy StructuredGrid-like object exposing ``nrow`` and ``ncol``.
    cell_samples_per_axis:
        Optional override for geology sub-sampling density.
        Higher values better resolve boundaries, at higher cost.
    depth:
        Depth offset added to layer-center depths for 3D evaluation.
        The same value is also used for legacy 2D output (backward compatibility).
    strict_field_spatial_id_match:
        If true, enforce consistency between heterogeneous
        ``field_param.field_spatial_id`` and ``geology_field.identifier``.
    """
    # 1) Interface guards.
    # Fail fast here to avoid cryptic attribute errors deeper in the pipeline.
    if not hasattr(geology_field, "on_mesh"):
        raise TypeError("geology_field must expose `on_mesh(...)`")
    if not hasattr(geology_field, "identifier"):
        raise TypeError("geology_field must expose `identifier`")
    if not hasattr(field_param, "to_mesh_field"):
        raise TypeError("field_param must expose `to_mesh_field(...)`")

    # 2) Business-consistency check for heterogeneous mapping.
    # Without this check, values could be mapped with the wrong spatial support.
    if bool(getattr(field_param, "is_heterogeneous", False)) and strict_field_spatial_id_match:
        required_field_id = str(getattr(field_param, "field_spatial_id", "")).strip()
        geology_field_id = str(getattr(geology_field, "identifier", "")).strip()
        if required_field_id and geology_field_id and required_field_id != geology_field_id:
            raise ValueError(
                "field_param.field_spatial_id does not match geology_field.identifier: "
                f"{required_field_id!r} != {geology_field_id!r}"
            )

    # 3) Solver-grid adapter.
    # Build a planar mesh view (XY only) consumed by geology_field.on_mesh(...).
    # Vertical resolution is handled later through layer-center depth evaluation.
    mesh = build_field_mesh_from_sgrid(sgrid)
    default_n_sub = int(getattr(geology_field, "default_cell_samples_per_axis", 8))
    # Sub-sampling density controls zone-fraction accuracy inside each cell.
    # Enforce >=2 to keep a meaningful 2D sampling pattern.
    n_sub = max(2, int(cell_samples_per_axis or default_n_sub))

    # 4) Geometry projection (geology -> weighted fractions by zone and cell).
    # `field_discretization` is not the final parameter grid.
    # It is an intermediate spatial object that stores, for each mesh cell:
    # - the list of zone keys seen in the geology field,
    # - one fraction per zone key (between 0 and 1),
    # - the target mesh reference.
    # Example (one cell):
    #   {"granite": 0.70, "schist": 0.30}
    # This object is then consumed by `field_param.to_mesh_field(...)` to
    # compute actual scalar values using weighted aggregation.
    field_discretization = geology_field.on_mesh(
        mesh,
        cell_samples_per_axis=n_sub,
    )

    # 5) Read target SGrid dimensions.
    # These dimensions define the canonical solver tensor layout used
    # downstream by MODFLOW-style packages:
    # - axis 0: vertical layers
    # - axis 1: rows
    # - axis 2: columns
    nlay = int(getattr(sgrid, "nlay"))
    nrow = int(getattr(sgrid, "nrow"))
    ncol = int(getattr(sgrid, "ncol"))

    # 6) Keep legacy planar output for current example visualizations.
    # Why this branch still exists:
    # - historical demos and QA figures consume a 2D map,
    # - users expect identical planar behavior during migration to 3D.
    #
    # Semantics of `depth` here (unchanged):
    # - scalar offset applied uniformly to the full 2D map before plotting/export.
    #
    # IMPORTANT:
    # `field_param.to_mesh_field(...)` returns values on the *current mesh support*.
    # Here this support is planar (nrow, ncol), so this call returns a 2D map.
    values_mesh_2d = field_param.to_mesh_field(field_discretization, depth=float(depth))
    values_2d = np.asarray(values_mesh_2d.cell_values, dtype=float)
    values_2d = np.asarray(mesh.to_cell_values(values_2d), dtype=float).reshape((nrow, ncol))

    # 7) Build full 3D values by layer-wise evaluation on SGrid depths.
    # Important design point:
    # - geology fractions remain horizontal (2D support),
    # - vertical variation is introduced through depth-dependent FieldParam logic.
    #
    # `layer_center_depths` is computed from (top, botm) and gives, for each
    # (layer,row,col), a positive-downward depth at the cell center.
    # A global scalar depth offset is then added (same semantics as before).
    layer_center_depths = _compute_layer_center_depths(sgrid) + float(depth)
    if layer_center_depths.shape != (nlay, nrow, ncol):
        raise ValueError(
            "Layer depth shape mismatch with SGrid dimensions: "
            f"{layer_center_depths.shape} vs {(nlay, nrow, ncol)}"
        )

    # Allocate final solver-ready tensor.
    # Each ilay slice is a full (nrow, ncol) map at that layer-center depth.
    # This is where volumetric information is assembled: by stacking multiple
    # depth-evaluated 2D outputs from `to_mesh_field`, not by a native 3D mesh.
    values_3d = np.empty((nlay, nrow, ncol), dtype=float)
    for ilay in range(nlay):
        # Extract one 2D depth field for the current layer.
        layer_depth = np.asarray(layer_center_depths[ilay, :, :], dtype=float)
        # Evaluate parameter values at this exact depth field.
        # For parameters without vertical variation, this naturally collapses to
        # the same 2D surface map across all layers.
        # Returned object still contains one value per 2D mesh cell.
        values_mesh_layer = field_param.to_mesh_field(
            field_discretization,
            depth=layer_depth,
        )
        # Normalize to canonical planar shape and place into the 3D tensor.
        layer_values = np.asarray(values_mesh_layer.cell_values, dtype=float)
        layer_values = np.asarray(mesh.to_cell_values(layer_values), dtype=float)
        values_3d[ilay, :, :] = layer_values.reshape((nrow, ncol))

    return SGridFieldParamDiscretizationResult(
        values_3d=values_3d,
        values_2d=values_2d,
        mesh=mesh,
        field_discretization=field_discretization,
    )
