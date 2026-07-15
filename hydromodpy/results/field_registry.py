"""Canonical field registry for HydroModPy simulation outputs.

A single source of truth that maps each public field name (used by figures,
CLI exports and the Python API) to its Zarr storage path and a CF-1.11
metadata bundle (standard_name, long_name, units, cell_methods, coordinates,
grid_mapping).

Downstream code (Zarr writers, xarray exporters, display modules) reads from
this registry so that the same field is described identically no matter which
layer produces or consumes it. Spec refs: ``architecture_cible/13_coherence_globale.md``
§1.3 and ``architecture_cible/04_storage_ideal.md`` §3.

The registry is intentionally small and explicit: when a new field is
introduced, add it here so every layer picks up the CF metadata for free.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.core.exceptions import UnknownFieldError

# Supported shape literals, exposed as constants so callers don't have to
# remember the exact strings. These are CF / UGRID shape signatures.
SHAPE_TIME_LAYER_FACE = "time_layer_face"
SHAPE_TIME_FACE = "time_face"
SHAPE_LAYER_FACE = "layer_face"
SHAPE_FACE = "face"
SHAPE_PARTICLES = "particles"

_SHAPE_TO_COORDINATES = {
    SHAPE_TIME_LAYER_FACE: "time layer face",
    SHAPE_TIME_FACE: "time face",
    SHAPE_LAYER_FACE: "layer face",
    SHAPE_FACE: "face",
    SHAPE_PARTICLES: "time particle",
}

# Face-aligned shapes also carry UGRID-1.0 ``mesh`` and ``location`` attrs
# pointing at the simulation's mesh topology variable.
_FACE_SHAPES = frozenset({SHAPE_TIME_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_LAYER_FACE, SHAPE_FACE})
UGRID_MESH_VARIABLE = "mesh/topology"


@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    """CF-1.11 compliant descriptor for a canonical HydroModPy field.

    Parameters
    ----------
    public_name:
        The name exposed to users in figures, exports, and the Python API.
    zarr_path:
        Relative Zarr path inside the simulation store (e.g. ``head`` or
        ``derived/watertable_depth``).
    standard_name:
        CF-1.11 ``standard_name`` attribute.
    long_name:
        Human-readable description (``long_name`` attribute).
    units:
        udunits / pint-compatible unit string (``units`` attribute). Use
        ``"1"`` for dimensionless quantities.
    shape:
        Canonical shape signature (one of the ``SHAPE_*`` constants).
    cell_methods:
        CF ``cell_methods`` attribute describing aggregation semantics.
    grid_mapping:
        Name of the CF ``grid_mapping`` variable in the Zarr store
        (defaults to ``"crs"``).
    derived_by:
        Either ``"solver"`` (written by a solver adapter) or ``"core"``
        (derived by :mod:`hydromodpy.results.derive.derived`).
    description:
        Free-form description used as fallback when the CF long_name is
        insufficient.
    """

    public_name: str
    zarr_path: str
    standard_name: str
    long_name: str
    units: str
    shape: str
    cell_methods: str = "time: point area: mean"
    grid_mapping: str = "crs"
    derived_by: str = "core"
    description: str = ""
    csdms_standard_name: str = ""
    valid_min: float | None = None
    valid_max: float | None = None

    @property
    def coordinates(self) -> str:
        """CF ``coordinates`` attribute derived from :attr:`shape`."""
        return _SHAPE_TO_COORDINATES.get(self.shape, self.shape)


FIELD_REGISTRY: dict[str, FieldDescriptor] = {
    # -- Primary state variables (written by solver adapters) ----------------
    # NOTE on ``standard_name``: only entries whose value is in the CF v85
    # vocabulary (see ``cf_validation.is_cf_standard_name``) carry a non-empty
    # ``standard_name``. Hydrogeology concepts absent from CF v85 ship an empty
    # CF ``standard_name`` and a CSDMS fallback under ``csdms_standard_name``;
    # downstream readers must consult that field when CF is empty.
    "head": FieldDescriptor(
        public_name="head",
        zarr_path="head",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_head",
        long_name="Groundwater head (per layer and UGRID face)",
        units="m",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: point area: mean",
        derived_by="solver",
    ),
    "concentration": FieldDescriptor(
        public_name="concentration",
        zarr_path="concentration",
        standard_name="",
        csdms_standard_name="subsurface_water__mass_concentration",
        long_name="Solute mass concentration in groundwater",
        units="kg m-3",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: point area: mean",
        derived_by="solver",
        valid_min=0.0,
    ),
    # -- Derived watertable variables (core postprocess) ---------------------
    "watertable_elevation": FieldDescriptor(
        public_name="watertable_elevation",
        zarr_path="derived/watertable_elevation",
        standard_name="",
        csdms_standard_name="subsurface_water_top_surface__elevation",
        long_name="Altitude of the water table (topmost saturated layer)",
        units="m",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: point area: mean",
        derived_by="core",
    ),
    "watertable_depth": FieldDescriptor(
        public_name="watertable_depth",
        zarr_path="derived/watertable_depth",
        standard_name="",
        csdms_standard_name="subsurface_water_top_surface__depth",
        long_name="Depth of the water table below land surface",
        units="m",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: point area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "seepage_mask": FieldDescriptor(
        public_name="seepage_mask",
        zarr_path="derived/seepage_mask",
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_binary_indicator",
        long_name="Binary mask of seepage cells (1 where water table outcrops)",
        units="1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: point area: maximum",
        derived_by="core",
        valid_min=0.0,
        valid_max=1.0,
    ),
    "seepage_rate": FieldDescriptor(
        public_name="seepage_rate",
        zarr_path="derived/seepage_rate",
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_volume_flux",
        long_name="Rate of groundwater seepage at land surface",
        units="m s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="core",
    ),
    "storage_change": FieldDescriptor(
        public_name="storage_change",
        zarr_path="derived/storage_change",
        standard_name="",
        csdms_standard_name="subsurface_water_storage__derivative_of_volume",
        long_name="Change in groundwater storage per unit time",
        units="m s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="core",
    ),
    # -- Budget fluxes (written from solver budget output) -------------------
    "recharge": FieldDescriptor(
        public_name="recharge",
        zarr_path="budget/recharge",
        standard_name="",
        csdms_standard_name="subsurface_water__recharge_volume_flux",
        long_name="Groundwater recharge volumetric flux",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "drain": FieldDescriptor(
        public_name="drain",
        zarr_path="budget/drain",
        standard_name="",
        csdms_standard_name="subsurface_water__drain_volume_flux",
        long_name="Groundwater flux to drains (positive leaves aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "outflow_drain": FieldDescriptor(
        public_name="outflow_drain",
        zarr_path="derived/outflow_drain",
        standard_name="",
        csdms_standard_name="subsurface_water__outflow_volume_flux",
        long_name="Positive groundwater outflow to drains summed over layers",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: sum",
        derived_by="core",
    ),
    "release_flux": FieldDescriptor(
        public_name="release_flux",
        zarr_path="derived/release_flux",
        standard_name="",
        csdms_standard_name="subsurface_water__release_volume_flux",
        long_name="Positive groundwater release flux to drains or land surface",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: sum",
        derived_by="core",
    ),
    "accumulation_flux": FieldDescriptor(
        public_name="accumulation_flux",
        zarr_path="derived/accumulation_flux",
        standard_name="",
        csdms_standard_name="subsurface_water__accumulation_volume_flux",
        long_name="Drain outflow accumulated along the drainage network",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: sum",
        derived_by="core",
    ),
    "release_accumulation_flux": FieldDescriptor(
        public_name="release_accumulation_flux",
        zarr_path="derived/release_accumulation_flux",
        standard_name="",
        csdms_standard_name="subsurface_water__release_accumulation_volume_flux",
        long_name="Groundwater release flux accumulated along surface drainage paths",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: sum",
        derived_by="core",
    ),
    "river": FieldDescriptor(
        public_name="river",
        zarr_path="budget/river",
        standard_name="",
        csdms_standard_name="subsurface_water__river_exchange_volume_flux",
        long_name="River leakage flux (positive enters aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "well": FieldDescriptor(
        public_name="well",
        zarr_path="budget/well",
        standard_name="",
        csdms_standard_name="subsurface_water__well_volume_flux",
        long_name="Well withdrawal or injection flux",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "surface_excess": FieldDescriptor(
        public_name="surface_excess",
        zarr_path="budget/surface_excess",
        standard_name="",
        csdms_standard_name="land_surface__saturation_excess_volume_flux",
        long_name="Saturation-excess outflow volumetric flux",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "cell_budget": FieldDescriptor(
        public_name="cell_budget",
        zarr_path="budget/cell_budget",
        standard_name="",
        csdms_standard_name="subsurface_water__mass_balance_residual_volume_flux",
        long_name="Per-cell water balance residual",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: sum",
        derived_by="solver",
    ),
    # -- Static inputs (geology, geometry) -----------------------------------
    "topography": FieldDescriptor(
        public_name="topography",
        zarr_path="mesh/topography",
        # CF v85: surface_altitude, canonical units m.
        standard_name="surface_altitude",
        csdms_standard_name="land_surface__elevation",
        long_name="Land surface elevation at mesh faces",
        units="m",
        shape=SHAPE_FACE,
        cell_methods="area: mean",
        derived_by="core",
    ),
    "layer_thickness": FieldDescriptor(
        public_name="layer_thickness",
        zarr_path="mesh/layer_thickness",
        # CF v85: cell_thickness.
        standard_name="cell_thickness",
        csdms_standard_name="subsurface_layer__thickness",
        long_name="Layer thickness at mesh faces",
        units="m",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "hydraulic_conductivity": FieldDescriptor(
        public_name="hydraulic_conductivity",
        zarr_path="derived/hydraulic_conductivity",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity",
        long_name="Saturated hydraulic conductivity",
        units="m s-1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "specific_yield": FieldDescriptor(
        public_name="specific_yield",
        zarr_path="derived/specific_yield",
        standard_name="",
        csdms_standard_name="subsurface_water__specific_yield",
        long_name="Specific yield (unconfined storage coefficient)",
        units="1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
        valid_max=1.0,
    ),
    "specific_storage": FieldDescriptor(
        public_name="specific_storage",
        zarr_path="derived/specific_storage",
        standard_name="",
        csdms_standard_name="subsurface_water__specific_storage_coefficient",
        long_name="Specific storage (confined storage coefficient)",
        units="m-1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "porosity": FieldDescriptor(
        public_name="porosity",
        zarr_path="derived/porosity",
        standard_name="",
        csdms_standard_name="subsurface_water__effective_porosity",
        long_name="Effective porosity of the porous medium",
        units="1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
        valid_max=1.0,
    ),
}


def get(name: str) -> FieldDescriptor:
    """Return the :class:`FieldDescriptor` registered under ``name``.

    Raises :class:`~hydromodpy.core.exceptions.UnknownFieldError` carrying the
    full list of available names when the lookup fails, which makes typos
    immediately actionable.
    """
    try:
        return FIELD_REGISTRY[name]
    except KeyError:
        raise UnknownFieldError(name, FIELD_REGISTRY.keys()) from None


def has(name: str) -> bool:
    """Return True when ``name`` is registered."""
    return name in FIELD_REGISTRY


def all_names() -> list[str]:
    """Return the sorted list of registered public names."""
    return sorted(FIELD_REGISTRY)


def all_zarr_paths() -> list[str]:
    """Return the sorted list of registered Zarr paths."""
    return sorted(desc.zarr_path for desc in FIELD_REGISTRY.values())


def cf_attrs(name: str) -> dict[str, object]:
    """Return a dict of CF-1.11 + UGRID-1.0 attributes for the given public name.

    Face-aligned variables additionally receive ``mesh`` and ``location``
    UGRID attributes so that xugrid / xarray readers can resolve the
    simulation topology automatically. ``standard_name`` is dropped from
    the result when the descriptor leaves it empty (CF v85 has no entry
    for the concept) -- ``csdms_standard_name`` carries the semantic name
    instead. The resulting mapping is suitable for
    ``zarr.Array.attrs.update(...)`` or as an xarray ``attrs=`` argument.
    """
    desc = get(name)
    attrs: dict[str, object] = {
        "long_name": desc.long_name,
        "units": desc.units,
        "cell_methods": desc.cell_methods,
        "grid_mapping": desc.grid_mapping,
        "coordinates": desc.coordinates,
    }
    if desc.standard_name:
        attrs["standard_name"] = desc.standard_name
    if desc.csdms_standard_name:
        attrs["csdms_standard_name"] = desc.csdms_standard_name
    if desc.valid_min is not None:
        attrs["valid_min"] = float(desc.valid_min)
    if desc.valid_max is not None:
        attrs["valid_max"] = float(desc.valid_max)
    if desc.shape in _FACE_SHAPES:
        attrs["mesh"] = UGRID_MESH_VARIABLE
        attrs["location"] = "face"
    return attrs


__all__ = [
    "SHAPE_TIME_LAYER_FACE",
    "SHAPE_TIME_FACE",
    "SHAPE_LAYER_FACE",
    "SHAPE_FACE",
    "SHAPE_PARTICLES",
    "UGRID_MESH_VARIABLE",
    "FieldDescriptor",
    "FIELD_REGISTRY",
    "get",
    "has",
    "all_names",
    "all_zarr_paths",
    "cf_attrs",
]
