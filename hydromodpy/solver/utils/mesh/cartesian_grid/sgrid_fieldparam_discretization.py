"""Core discretization primitives for planar-to-3D extrusion of FieldParam on one SGrid.

Design note
-----------
The mesh adapter used here is intentionally planar (2D XY support), and the
3D result is produced by extrusion:
- spatial support is discretized on 2D cells when heterogeneous mapping is used,
- values are then evaluated on all SGrid layers using layer-center depths.

As a result:
- `values_3d` is the main solver-ready output,
- `values_2d` provides one planar reference map on the same support.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.field.meshes import StructuredFieldMesh
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter import (
    build_field_mesh_from_sgrid,
)


@dataclass(frozen=True)
class SGridFieldParamDiscretizationResult:
    """Result bundle for one discretization run.

    values_3d:
        Final 3D array (nlay, nrow, ncol) aligned with the full SGrid.
    values_2d:
        Planar reference array (nrow, ncol) evaluated on the same mesh support.
    mesh:
        Intermediate field mesh used for planar support projection.
    field_discretization:
        Output of ``support_field.on_mesh(...)`` (zone fractions) when a
        heterogeneous support is used, else ``None``.
    """

    values_3d: np.ndarray
    values_2d: np.ndarray
    mesh: StructuredFieldMesh
    field_discretization: object


def _compute_layer_center_depths(sgrid) -> np.ndarray:
    """Return positive-downward depth at each layer center.

    The depth reference is the local model top (depth=0 at surface):
    ``depth = top - 0.5 * (ztop_layer + zbot_layer)``.

    Accepts both FloPy StructuredGrid (3D botm) and SolverMesh (flat arrays
    with reshape helpers).
    """
    # SolverMesh exposes top_grid/botm_grid for reshaped structured views.
    if hasattr(sgrid, "top_grid") and hasattr(sgrid, "botm_grid"):
        top = np.asarray(sgrid.top_grid, dtype=float)
        botm = np.asarray(sgrid.botm_grid, dtype=float)
    else:
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
    support_field=None,
    field_param,
    sgrid,
    geometry_cache: dict[
        tuple[object, ...],
        tuple[StructuredFieldMesh, object | None, np.ndarray],
    ]
    | None = None,
    cell_samples_per_axis: int | None = None,
    depth: float = 0.0,
    strict_field_spatial_id_match: bool = True,
    geology_field=None,
) -> SGridFieldParamDiscretizationResult:
    """Discretize one ``FieldParam`` on one structured solver grid.

    Why this function is central
    ----------------------------
    This is the core bridge between:
    - an optional spatial support (``support_field``),
    - a parameter definition (``field_param``),
    - and the solver grid layout (``sgrid``).

    The function performs two different operations that are often confused:
    1) *Geometry projection*: estimate support-zone fractions inside each cell.
    2) *Value mapping*: convert those fractions into numeric parameter values.

    Step-by-step workflow
    ---------------------
    1) Validate minimal runtime contracts on input objects.
    2) Convert the solver ``sgrid`` to a generic field mesh.
    3) Project the spatial support on this mesh with sub-sampling when needed.
    4) Ask ``field_param`` to compute planar values per mesh cell.
    5) Evaluate those values over all SGrid layers (full 3D).
    6) Return both a planar reference map and full 3D values.

    Parameters
    ----------
    support_field:
        Optional object exposing ``identifier`` and ``on_mesh(mesh, ...)``.
        Required for heterogeneous fields. Not used for homogeneous fields.
    field_param:
        Object exposing ``to_mesh_field(...)`` and optional heterogeneous metadata.
    sgrid:
        Structured grid object exposing ``nrow``, ``ncol``, and vertex
        coordinates.  Accepts both FloPy ``StructuredGrid`` and ``SolverMesh``.
    cell_samples_per_axis:
        Optional override for support-field sub-sampling density.
        Higher values better resolve boundaries, at higher cost.
    depth:
        Depth offset added to layer-center depths for 3D evaluation.
        The same value is also used for the planar reference map.
    strict_field_spatial_id_match:
        If true, enforce consistency between heterogeneous
        ``field_param.field_spatial_id`` and ``support_field.identifier``.
    """
    if support_field is not None and geology_field is not None:
        raise ValueError(
            "Use either 'support_field' or legacy 'geology_field', not both."
        )
    if support_field is None:
        support_field = geology_field

    # 1) Interface guards.
    # Fail fast here to avoid cryptic attribute errors deeper in the pipeline.
    if not hasattr(field_param, "to_mesh_field"):
        raise TypeError("field_param must expose `to_mesh_field(...)`")

    is_heterogeneous = bool(getattr(field_param, "is_heterogeneous", False))
    if is_heterogeneous and support_field is None:
        raise ValueError("Heterogeneous field requires 'support_field'")
    if support_field is not None and not hasattr(support_field, "on_mesh"):
        raise TypeError("support_field must expose `on_mesh(...)`")
    if support_field is not None and not hasattr(support_field, "identifier"):
        raise TypeError("support_field must expose `identifier`")

    # 2) Business-consistency check for heterogeneous mapping.
    # Without this check, values could be mapped with the wrong spatial support.
    if is_heterogeneous and strict_field_spatial_id_match:
        required_field_id = str(getattr(field_param, "field_spatial_id", "")).strip()
        support_field_id = str(getattr(support_field, "identifier", "")).strip()
        if required_field_id and support_field_id and required_field_id != support_field_id:
            raise ValueError(
                "field_param.field_spatial_id does not match support_field.identifier: "
                f"{required_field_id!r} != {support_field_id!r}"
            )

    default_n_sub = int(getattr(support_field, "default_cell_samples_per_axis", 8))
    # Sub-sampling density controls zone-fraction accuracy inside each cell.
    # Enforce >=2 to keep a meaningful 2D sampling pattern.
    n_sub = max(2, int(cell_samples_per_axis or default_n_sub))

    # 3) Solver-grid adapter + geometry projection.
    # Geometry projection is only needed for heterogeneous fields.
    # Reuse it from a per-run cache when available.
    cache_key = (
        ("support", id(support_field), id(sgrid), int(n_sub))
        if support_field is not None
        else ("mesh", id(sgrid))
    )
    cached = geometry_cache.get(cache_key) if geometry_cache is not None else None
    if cached is None:
        # Build a planar mesh view (XY only) consumed by support_field.on_mesh(...).
        # Vertical resolution is handled later through layer-center depth evaluation.
        mesh = build_field_mesh_from_sgrid(sgrid)
        field_discretization = None
        if support_field is not None:
            # `field_discretization` is not the final parameter grid.
            # It is an intermediate spatial object that stores, for each mesh cell:
            # - the list of zone keys seen in the support field,
            # - one fraction per zone key (between 0 and 1),
            # - the target mesh reference.
            field_discretization = support_field.on_mesh(
                mesh,
                cell_samples_per_axis=n_sub,
            )
        layer_center_depths_base = _compute_layer_center_depths(sgrid)
        if geometry_cache is not None:
            geometry_cache[cache_key] = (
                mesh,
                field_discretization,
                layer_center_depths_base,
            )
    else:
        mesh, field_discretization, layer_center_depths_base = cached

    # 5) Read target SGrid dimensions.
    # These dimensions define the canonical solver tensor layout used
    # downstream by MODFLOW-style packages:
    # - axis 0: vertical layers
    # - axis 1: rows
    # - axis 2: columns
    nlay = int(getattr(sgrid, "nlay"))
    nrow = int(getattr(sgrid, "nrow"))
    ncol = int(getattr(sgrid, "ncol"))

    # 6) Build the planar reference map on the mesh support.
    # This output is useful for plan-view QA/plots and complements the 3D tensor.
    #
    # Semantics of `depth`:
    # - scalar offset applied uniformly to the 2D map before plotting/export.
    #
    # IMPORTANT:
    # `field_param.to_mesh_field(...)` returns values on the *current mesh support*.
    # Here this support is planar (nrow, ncol), so this call returns a 2D map.
    if field_discretization is None:
        values_mesh_2d = field_param.to_mesh_field(mesh=mesh, depth=float(depth))
    else:
        values_mesh_2d = field_param.to_mesh_field(
            field_discretization,
            depth=float(depth),
        )
    values_2d = np.asarray(values_mesh_2d.cell_values, dtype=float)
    values_2d = np.asarray(mesh.to_cell_values(values_2d), dtype=float).reshape((nrow, ncol))

    # 7) Build full 3D values by layer-wise evaluation on SGrid depths.
    # Important design point:
    # - support fractions remain horizontal (2D support),
    # - vertical variation is introduced through depth-dependent FieldParam logic.
    #
    # `layer_center_depths` is computed from (top, botm) and gives, for each
    # (layer,row,col), a positive-downward depth at the cell center.
    # A global scalar depth offset is then added (same semantics as before).
    layer_center_depths = np.asarray(layer_center_depths_base, dtype=float) + float(depth)
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
        if field_discretization is None:
            values_mesh_layer = field_param.to_mesh_field(
                mesh=mesh,
                depth=layer_depth,
            )
        else:
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
