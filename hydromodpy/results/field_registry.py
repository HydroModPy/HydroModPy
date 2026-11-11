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
SHAPE_TIME = "time"
SHAPE_LAYER_FACE = "layer_face"
SHAPE_FACE = "face"
SHAPE_PARTICLES = "particles"
SHAPE_TIME_CONNECTION = "time_connection"
SHAPE_CONNECTION_PAIR = "connection_pair"

# Axis vocabulary of a run store. Zarr v3 records the axis names of an array in
# ``dimension_names``; without them no reader can tell which axis of a
# ``(1, 10, 63)`` array is time, and ``xarray.open_zarr`` refuses the store. The
# vocabulary is closed and lives here, beside the CF metadata it must agree with.
AXIS_TIME = "time"
AXIS_LAYER = "layer"
AXIS_FACE = "face"
AXIS_NODE = "node"
AXIS_NODE_COORDINATE = "node_coordinate"
AXIS_MAX_FACE_NODES = "max_face_nodes"
AXIS_LAYER_INTERFACE = "layer_interface"
AXIS_PARTICLE = "particle"
AXIS_TRACK_STEP = "track_step"
AXIS_ENDPOINT = "endpoint"
AXIS_RECORD = "record"
AXIS_SOIL_COLUMN = "soil_column"
AXIS_LAKE = "lake"
AXIS_STAGE_LEVEL = "stage_level"
AXIS_EDGE = "edge"
AXIS_TWO = "two"
AXIS_CONNECTION = "connection"

_SHAPE_TO_DIMENSIONS: dict[str, tuple[str, ...]] = {
    SHAPE_TIME_LAYER_FACE: (AXIS_TIME, AXIS_LAYER, AXIS_FACE),
    SHAPE_TIME_FACE: (AXIS_TIME, AXIS_FACE),
    SHAPE_LAYER_FACE: (AXIS_LAYER, AXIS_FACE),
    SHAPE_FACE: (AXIS_FACE,),
    SHAPE_PARTICLES: (AXIS_PARTICLE, AXIS_TRACK_STEP),
    SHAPE_TIME_CONNECTION: (AXIS_TIME, AXIS_CONNECTION),
    SHAPE_CONNECTION_PAIR: (AXIS_CONNECTION, AXIS_TWO),
}

_SHAPE_TO_COORDINATES = {
    signature: " ".join(names) for signature, names in _SHAPE_TO_DIMENSIONS.items()
}

# Face-aligned shapes also carry UGRID-1.0 ``mesh`` and ``location`` attrs
# pointing at the simulation's mesh topology variable.
_FACE_SHAPES = frozenset({SHAPE_TIME_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_LAYER_FACE, SHAPE_FACE})
UGRID_MESH_VARIABLE = "mesh/topology"
BUDGET_GROUP = "budget/"
NOT_AQUIFER_TERMS = frozenset({"lake_to_mover", "stream_to_mover", "mover"})
"""Budget records of the surface side of the water mover, which keep the sign MODFLOW 6 gives them."""

FACE_FLOW = "face_flow"
"""Registry name of the flow between two connected cells, the product a transport reads."""

CONNECTION_CELLS = "connection_cells"
"""Registry name of the two cells of each connection, the smaller flat index first."""


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
    def timed(self) -> bool:
        """Whether the field carries a leading time axis."""
        return self.shape.startswith("time")

    @property
    def dimensions(self) -> tuple[str, ...]:
        """Zarr ``dimension_names`` derived from :attr:`shape`."""
        return _SHAPE_TO_DIMENSIONS.get(self.shape, (self.shape,))

    @property
    def coordinates(self) -> str:
        """CF ``coordinates`` attribute derived from :attr:`shape`.

        CF-1.11 §5 permits a variable to list its own dimension coordinates
        here, and every name it lists is a real array at the root of the store.
        """
        return " ".join(self.dimensions)


@dataclass(frozen=True, slots=True)
class TimeSeriesDescriptor:
    """CF-1.11 descriptor of a station series written in ``timeseries.parquet``.

    A series of shape :data:`SHAPE_TIME` holds one value per time step of one
    station, so it has no Zarr array: ``zarr_dimension_names`` and
    ``cf_coordinates`` describe fields and do not apply here. A series that
    samples a registered field at one point, ``head`` of an observation point
    for example, is described by that field and carries no entry.
    """

    public_name: str
    long_name: str
    units: str
    shape: str = SHAPE_TIME
    standard_name: str = ""
    description: str = ""


BUDGET_SIGN_RULE = "positive enters the aquifer, negative leaves it"
"""The sign of every field under ``budget/``, the one MODFLOW gives a budget, for every solver."""

FIELD_REGISTRY: dict[str, FieldDescriptor] = {
    # -- Primary state variables (written by solver adapters) ----------------
    # NOTE on ``standard_name``: only entries whose value is in the CF v85
    # vocabulary (see ``cf_validation.is_cf_standard_name``) carry a non-empty
    # ``standard_name``. CF has no hydraulic head, no specific yield and no cell
    # budget flux of an aquifer, and its names for fluxes are per unit area
    # (kg m-2 s-1), which a cell flux in m3 s-1 cannot take. ``soil_porosity`` and
    # ``soil_hydraulic_conductivity_at_saturation`` describe a soil, not an
    # aquifer. Those fields ship an empty CF ``standard_name`` and a CSDMS fallback
    # under ``csdms_standard_name``; downstream readers must consult that field
    # when CF is empty.
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
        long_name=(
            "Solute mass concentration in groundwater, one solute per run, "
            "read under concentration/<spc_name> or, for a run written by 2.0.0, "
            "under the flat concentration array"
        ),
        units="kg m-3",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: point area: mean",
        derived_by="solver",
        valid_min=0.0,
    ),
    # -- Connection geometry and flow (written by solver adapters) ------------
    FACE_FLOW: FieldDescriptor(
        public_name=FACE_FLOW,
        zarr_path=FACE_FLOW,
        standard_name="",
        csdms_standard_name="subsurface_water__volume_flux",
        long_name=(
            "Volume flow from the first to the second cell of each connection, "
            "mean of the steps of each saved period"
        ),
        units="m3 s-1",
        shape=SHAPE_TIME_CONNECTION,
        cell_methods="time: mean",
        derived_by="solver",
    ),
    CONNECTION_CELLS: FieldDescriptor(
        public_name=CONNECTION_CELLS,
        zarr_path=CONNECTION_CELLS,
        standard_name="",
        csdms_standard_name="model_grid_cell__index",
        long_name=(
            "Flat index (layer x faces + face) of the two cells of each connection, "
            "the smaller first"
        ),
        units="1",
        shape=SHAPE_CONNECTION_PAIR,
        cell_methods="area: point",
        derived_by="solver",
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
        # CF v85: water_table_depth, canonical units m.
        standard_name="water_table_depth",
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
    # -- Budget fluxes (written from solver budget output) -------------------
    "recharge": FieldDescriptor(
        public_name="recharge",
        zarr_path="budget/recharge",
        standard_name="",
        csdms_standard_name="subsurface_water__recharge_volume_flux",
        long_name="Groundwater recharge volumetric flux (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "drain": FieldDescriptor(
        public_name="drain",
        zarr_path="budget/drain",
        standard_name="",
        csdms_standard_name="subsurface_water__drain_volume_flux",
        long_name="Groundwater flux to drains (negative leaves the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "drain_to_mover": FieldDescriptor(
        public_name="drain_to_mover",
        zarr_path="budget/drain_to_mover",
        standard_name="",
        csdms_standard_name="subsurface_water__drain_volume_flux",
        long_name="Drain flux handed to the water mover (negative leaves the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "storage": FieldDescriptor(
        public_name="storage",
        zarr_path="budget/storage",
        standard_name="",
        csdms_standard_name="subsurface_water__storage_volume_flux",
        long_name="Storage term of the cell water balance (positive enters the aquifer from storage)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "storage_ss": FieldDescriptor(
        public_name="storage_ss",
        zarr_path="budget/storage_ss",
        standard_name="",
        csdms_standard_name="subsurface_water__specific_storage_volume_flux",
        long_name="Specific-storage term of the cell water balance (MODFLOW 6, positive enters the aquifer from storage)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "storage_sy": FieldDescriptor(
        public_name="storage_sy",
        zarr_path="budget/storage_sy",
        standard_name="",
        csdms_standard_name="subsurface_water__specific_yield_volume_flux",
        long_name="Specific-yield term of the cell water balance (MODFLOW 6, positive enters the aquifer from storage)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "evapotranspiration": FieldDescriptor(
        public_name="evapotranspiration",
        zarr_path="budget/evapotranspiration",
        standard_name="",
        csdms_standard_name="subsurface_water__evapotranspiration_volume_flux",
        long_name="Evapotranspiration flux drawn from the aquifer (negative leaves the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "general_head": FieldDescriptor(
        public_name="general_head",
        zarr_path="budget/general_head",
        standard_name="",
        csdms_standard_name="subsurface_water__general_head_volume_flux",
        long_name="Flux across general-head boundary cells (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "lake_to_mover": FieldDescriptor(
        public_name="lake_to_mover",
        zarr_path="budget/lake_to_mover",
        standard_name="",
        csdms_standard_name="subsurface_water__lake_to_mover_volume_flux",
        long_name="Lake outflow handed to the water mover, as MODFLOW 6 signs the record",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "stream_to_mover": FieldDescriptor(
        public_name="stream_to_mover",
        zarr_path="budget/stream_to_mover",
        standard_name="",
        csdms_standard_name="subsurface_water__stream_to_mover_volume_flux",
        long_name="Stream outflow handed to the water mover, as MODFLOW 6 signs the record",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "mover": FieldDescriptor(
        public_name="mover",
        zarr_path="budget/mover",
        standard_name="",
        csdms_standard_name="subsurface_water__mover_volume_flux",
        long_name="Flux of the water mover package, as MODFLOW 6 signs the record",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
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
    "drain_accumulation_flux": FieldDescriptor(
        public_name="drain_accumulation_flux",
        zarr_path="derived/drain_accumulation_flux",
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
    "budget_flux_per_area": FieldDescriptor(
        public_name="budget_flux_per_area",
        zarr_path="derived/budget_flux_per_area",
        standard_name="",
        csdms_standard_name="subsurface_water__budget_unit_area_volume_flux",
        long_name="One budget term (drain, else recharge) summed over layers per unit cell area, signed as the term",
        units="m s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="core",
    ),
    "concentration_seepage": FieldDescriptor(
        public_name="concentration_seepage",
        zarr_path="derived/concentration_seepage",
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_mass_concentration",
        long_name="Solute concentration at seepage cells, NaN elsewhere",
        units="kg m-3",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: point area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "mass_seepage": FieldDescriptor(
        public_name="mass_seepage",
        zarr_path="derived/mass_seepage",
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_mass_flux",
        long_name="Solute mass flux at seepage cells (seepage concentration times drain outflow)",
        units="kg s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="core",
    ),
    "mass_seepage_running_sum": FieldDescriptor(
        public_name="mass_seepage_running_sum",
        zarr_path="derived/mass_seepage_running_sum",
        standard_name="",
        csdms_standard_name="subsurface_water__seepage_accumulated_mass_flux",
        long_name="Running sum over the time steps of the solute mass flux at seepage cells, not a mass",
        units="kg s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
        derived_by="core",
    ),
    "river": FieldDescriptor(
        public_name="river",
        zarr_path="budget/river",
        standard_name="",
        csdms_standard_name="subsurface_water__river_exchange_volume_flux",
        long_name="River leakage flux (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "well": FieldDescriptor(
        public_name="well",
        zarr_path="budget/well",
        standard_name="",
        csdms_standard_name="subsurface_water__well_volume_flux",
        long_name="Well withdrawal or injection flux (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "stream": FieldDescriptor(
        public_name="stream",
        zarr_path="budget/stream",
        standard_name="",
        csdms_standard_name="subsurface_water__stream_exchange_volume_flux",
        long_name="Streambed leakage flux exchanged with the SFR network (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "lake": FieldDescriptor(
        public_name="lake",
        zarr_path="budget/lake",
        standard_name="",
        csdms_standard_name="subsurface_water__lake_exchange_volume_flux",
        long_name="Lakebed leakage flux exchanged with the LAK package (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "constant_head": FieldDescriptor(
        public_name="constant_head",
        zarr_path="budget/constant_head",
        standard_name="",
        csdms_standard_name="subsurface_water__constant_head_volume_flux",
        long_name="Flux across constant-head cells (positive enters the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_LAYER_FACE,
        cell_methods="time: mean area: mean",
        derived_by="solver",
    ),
    "constant_head_stream": FieldDescriptor(
        public_name="constant_head_stream",
        zarr_path="budget/constant_head_stream",
        standard_name="",
        csdms_standard_name="subsurface_water__stream_constant_head_volume_flux",
        long_name=(
            "Flux across the constant-head cells that carry the stream role "
            "(positive enters the aquifer), zero elsewhere"
        ),
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
        long_name="Saturation-excess flux at the land surface (negative leaves the aquifer)",
        units="m3 s-1",
        shape=SHAPE_TIME_FACE,
        cell_methods="time: mean area: mean",
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
    "streambed_top": FieldDescriptor(
        public_name="streambed_top",
        zarr_path="mesh/streambed_top",
        standard_name="altitude",
        csdms_standard_name="channel_bottom_water-sediment__elevation",
        long_name="SFR streambed top elevation, NaN where no reach",
        units="m",
        shape=SHAPE_FACE,
        cell_methods="area: point",
        derived_by="solver",
    ),
    "streambed_connection": FieldDescriptor(
        public_name="streambed_connection",
        zarr_path="mesh/streambed_connection",
        standard_name="altitude",
        csdms_standard_name="channel_bottom_water-sediment__elevation",
        long_name=(
            "Head below which an SFR reach disconnects from the aquifer "
            "(rtp - streambed thickness), NaN where no reach"
        ),
        units="m",
        shape=SHAPE_FACE,
        cell_methods="area: point",
        derived_by="solver",
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
    "idomain": FieldDescriptor(
        public_name="idomain",
        zarr_path="mesh/idomain",
        standard_name="",
        csdms_standard_name="subsurface_layer__activity_indicator",
        long_name="Cell activity of the layered model: 1 active, 0 inactive, -1 pass-through",
        units="1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: point",
        derived_by="solver",
        valid_min=-1.0,
        valid_max=1.0,
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
    "hydraulic_conductivity_k22": FieldDescriptor(
        public_name="hydraulic_conductivity_k22",
        zarr_path="derived/hydraulic_conductivity_k22",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity_second_axis",
        long_name="Hydraulic conductivity along the second axis of the K tensor (MODFLOW 6 K22)",
        units="m s-1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "hydraulic_conductivity_k33": FieldDescriptor(
        public_name="hydraulic_conductivity_k33",
        zarr_path="derived/hydraulic_conductivity_k33",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity_third_axis",
        long_name=(
            "Hydraulic conductivity along the third axis of the K tensor, vertical when "
            "the tensor is not tilted (MODFLOW 6 K33)"
        ),
        units="m s-1",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
        valid_min=0.0,
    ),
    "conductivity_tensor_angle1": FieldDescriptor(
        public_name="conductivity_tensor_angle1",
        zarr_path="derived/conductivity_tensor_angle1",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity_tensor_angle1",
        long_name="Turn of the first K axis from east towards north (MODFLOW 6 ANGLE1)",
        units="degree",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
    ),
    "conductivity_tensor_angle2": FieldDescriptor(
        public_name="conductivity_tensor_angle2",
        zarr_path="derived/conductivity_tensor_angle2",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity_tensor_angle2",
        long_name="Rise of the first K axis above the horizontal (MODFLOW 6 ANGLE2)",
        units="degree",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
    ),
    "conductivity_tensor_angle3": FieldDescriptor(
        public_name="conductivity_tensor_angle3",
        zarr_path="derived/conductivity_tensor_angle3",
        standard_name="",
        csdms_standard_name="subsurface_water__hydraulic_conductivity_tensor_angle3",
        long_name="Rotation of the K tensor about its first axis (MODFLOW 6 ANGLE3)",
        units="degree",
        shape=SHAPE_LAYER_FACE,
        cell_methods="area: mean",
        derived_by="core",
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


TIME_SERIES_REGISTRY: dict[str, TimeSeriesDescriptor] = {
    # Station series of ``timeseries.parquet``, one value per time step of one
    # station. They are what the catchment aggregation writes (in m3 s-1), the
    # state quantities the LAK and SFR extractors store, and the rates they
    # scale to m3 s-1. The ``storage`` of a lake is not a series name here: it
    # would collide with the budget field ``storage`` of the aquifer, and that
    # conflict is settled where it can be refused at write time.
    "discharge": TimeSeriesDescriptor(
        public_name="discharge",
        long_name="Water leaving the aquifer, summed over the catchment",
        units="m3 s-1",
        standard_name="water_volume_transport_in_river_channel",
    ),
    "well_pumping": TimeSeriesDescriptor(
        public_name="well_pumping",
        long_name="Well pumping, summed over the catchment",
        units="m3 s-1",
    ),
    "reservoir_storage": TimeSeriesDescriptor(
        public_name="reservoir_storage",
        long_name="Depth of water stored in the lumped reservoir of the catchment",
        units="m",
    ),
    # Lake states (the lake station is ``lake:<id>``).
    "stage": TimeSeriesDescriptor(
        public_name="stage",
        long_name="Water level of a lake or a stream reach",
        units="m",
    ),
    "volume": TimeSeriesDescriptor(
        public_name="volume",
        long_name="Water volume held by the lake",
        units="m3",
    ),
    "surface_area": TimeSeriesDescriptor(
        public_name="surface_area",
        long_name="Surface of the free water of the lake",
        units="m2",
    ),
    # Lake rates, positive into the lake, an outflow positive out of it.
    "gwf_exchange": TimeSeriesDescriptor(
        public_name="gwf_exchange",
        long_name="Water the aquifer gives the lake through its bed",
        units="m3 s-1",
    ),
    "lake_bed_vertical_exchange": TimeSeriesDescriptor(
        public_name="lake_bed_vertical_exchange",
        long_name="Vertical exchange through the lake bed",
        units="m3 s-1",
    ),
    "rainfall": TimeSeriesDescriptor(
        public_name="rainfall",
        long_name="Rainfall on the free water of the lake",
        units="m3 s-1",
    ),
    "evaporation": TimeSeriesDescriptor(
        public_name="evaporation",
        long_name="Evaporation from the free water of the lake",
        units="m3 s-1",
    ),
    "runoff": TimeSeriesDescriptor(
        public_name="runoff",
        long_name="Inland runoff the lake or the reach receives",
        units="m3 s-1",
    ),
    "inflow": TimeSeriesDescriptor(
        public_name="inflow",
        long_name="Inflow declared for the lake",
        units="m3 s-1",
    ),
    "withdrawal": TimeSeriesDescriptor(
        public_name="withdrawal",
        long_name="Water withdrawn from the lake",
        units="m3 s-1",
    ),
    "ext_outflow": TimeSeriesDescriptor(
        public_name="ext_outflow",
        long_name="Outflow the lake or the reach gives outside the model",
        units="m3 s-1",
    ),
    "outlet": TimeSeriesDescriptor(
        public_name="outlet",
        long_name="Outflow routed through the lake outlet",
        units="m3 s-1",
    ),
    "outlet_inflow": TimeSeriesDescriptor(
        public_name="outlet_inflow",
        long_name="Water the outlet of the lake receives from it",
        units="m3 s-1",
    ),
    "to_mvr": TimeSeriesDescriptor(
        public_name="to_mvr",
        long_name="Water forwarded to a mover by the lake or the reach",
        units="m3 s-1",
    ),
    "from_mvr": TimeSeriesDescriptor(
        public_name="from_mvr",
        long_name="Water received from a mover by the lake or the reach",
        units="m3 s-1",
    ),
    "lak_connection": TimeSeriesDescriptor(
        public_name="lak_connection",
        long_name="Exchange between two connected lakes",
        units="m3 s-1",
    ),
    # Stream reach states and rates (the reach station is ``<network>:<number>``).
    "depth": TimeSeriesDescriptor(
        public_name="depth",
        long_name="Water depth of a stream reach",
        units="m",
    ),
    "downstream_flow": TimeSeriesDescriptor(
        public_name="downstream_flow",
        long_name="Flow a downstream reach receives from this one",
        units="m3 s-1",
    ),
    "ext_inflow": TimeSeriesDescriptor(
        public_name="ext_inflow",
        long_name="Inflow the reach reads from outside the model",
        units="m3 s-1",
    ),
    "gw_exchange": TimeSeriesDescriptor(
        public_name="gw_exchange",
        long_name="Water exchanged between the aquifer and the reach",
        units="m3 s-1",
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


def is_time_resolved(name: str) -> bool:
    """Return whether the stored array of ``name`` has a leading time axis.

    Registered static geometry (``topography``, ``layer_thickness``) has none.
    An unregistered solver array is taken as time-resolved.
    """
    return not has(name) or FIELD_REGISTRY[name].timed


def all_names() -> list[str]:
    """Return the sorted list of registered public names."""
    return sorted(FIELD_REGISTRY)


def all_zarr_paths() -> list[str]:
    """Return the sorted list of registered Zarr paths."""
    return sorted(desc.zarr_path for desc in FIELD_REGISTRY.values())


def series_names() -> list[str]:
    """Return the sorted list of registered station series."""
    return sorted(TIME_SERIES_REGISTRY)


def series_unit(name: str) -> str:
    """Return the unit of the station series ``name``, ``""`` when unregistered.

    The writers of ``timeseries.parquet`` read the unit here, so a series and
    its unit live in one place; a variable the registry does not hold is
    written with an empty unit until its writer names it.
    """
    descriptor = TIME_SERIES_REGISTRY.get(name)
    return descriptor.units if descriptor is not None else ""


def timed_field_dimensions(ndim: int) -> tuple[str, ...]:
    """Return the axis names of a ``(time, ...)`` field array.

    The writer opens a field with a leading time axis and one or two spatial
    axes, so the rank alone determines the names.
    """
    if ndim == 2:
        return (AXIS_TIME, AXIS_FACE)
    if ndim == 3:
        return (AXIS_TIME, AXIS_LAYER, AXIS_FACE)
    raise ValueError(f"A timed field has 2 or 3 axes, got {ndim}")


def static_field_dimensions(ndim: int) -> tuple[str, ...]:
    """Return the axis names of a field array written once, with no time axis."""
    if ndim == 1:
        return (AXIS_FACE,)
    if ndim == 2:
        return (AXIS_LAYER, AXIS_FACE)
    raise ValueError(f"A static field has 1 or 2 axes, got {ndim}")


def per_array_dimensions(name: str, ndim: int) -> tuple[str, ...]:
    """Return axis names for an array that shares no axis with its siblings.

    A geographic raster carries its own affine transform, so its rows and
    columns are not the rows and columns of the raster beside it. Naming the
    axes after the array keeps the names honest and keeps the group openable.
    """
    return tuple(f"{name}_dim{index}" for index in range(ndim))


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
    if desc.zarr_path.startswith(BUDGET_GROUP) and name not in NOT_AQUIFER_TERMS:
        attrs["sign_convention"] = BUDGET_SIGN_RULE
    if desc.shape in _FACE_SHAPES:
        attrs["mesh"] = UGRID_MESH_VARIABLE
        attrs["location"] = "face"
    return attrs


__all__ = [
    "SHAPE_TIME_LAYER_FACE",
    "SHAPE_TIME_FACE",
    "SHAPE_TIME",
    "SHAPE_LAYER_FACE",
    "SHAPE_FACE",
    "SHAPE_PARTICLES",
    "SHAPE_TIME_CONNECTION",
    "SHAPE_CONNECTION_PAIR",
    "BUDGET_SIGN_RULE",
    "CONNECTION_CELLS",
    "FACE_FLOW",
    "UGRID_MESH_VARIABLE",
    "AXIS_CONNECTION",
    "AXIS_EDGE",
    "AXIS_ENDPOINT",
    "AXIS_FACE",
    "AXIS_LAKE",
    "AXIS_LAYER",
    "AXIS_LAYER_INTERFACE",
    "AXIS_MAX_FACE_NODES",
    "AXIS_NODE",
    "AXIS_NODE_COORDINATE",
    "AXIS_PARTICLE",
    "AXIS_RECORD",
    "AXIS_SOIL_COLUMN",
    "AXIS_STAGE_LEVEL",
    "AXIS_TIME",
    "AXIS_TRACK_STEP",
    "AXIS_TWO",
    "FieldDescriptor",
    "TIME_SERIES_REGISTRY",
    "TimeSeriesDescriptor",
    "FIELD_REGISTRY",
    "get",
    "per_array_dimensions",
    "static_field_dimensions",
    "timed_field_dimensions",
    "has",
    "is_time_resolved",
    "all_names",
    "all_zarr_paths",
    "cf_attrs",
    "series_names",
    "series_unit",
]
