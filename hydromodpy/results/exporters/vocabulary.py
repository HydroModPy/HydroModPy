"""The names a user can export, and the kind of each.

``[[export]] variables``, ``run.export`` and ``hmp export`` read one namespace.
It holds the mesh fields, the series, the vector layers, the raster layers and
the tables a run can store. The kind of a name decides its natural format and
the formats it can be written in
(:data:`~hydromodpy.results.exporters.export_spec.KIND_FORMATS`).

This module holds the static part: every name some run can hold, known before
any run exists. The step 0 check reads it to refuse a typo before the solve.
A name is looked up in the order ``hmp.read`` resolves it: the field registry
first, then the series, the vector layers, the raster layers and the tables.

The names are the stored ones. The series and layer names are written by
layers ``results`` may not import (``workflow``, ``solver``, ``data``), so
they are restated here; each group names the module that writes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
)
from hydromodpy.core.scope import OBSERVED, series_name
from hydromodpy.results import field_registry
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    available_virtual_fields,
)
from hydromodpy.results.exporters._tables import (
    BUDGETS_TABLE,
    TIMESERIES_TABLE,
    distinct_rows,
    geographic_features,
    table_rows,
)
from hydromodpy.results.exporters.export_spec import MESH_LAYERS, ExportKind
from hydromodpy.results.exporters.mesh_layers import available_mesh_layers

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

# results/derive/catchment_aggregation.py (catchment series)
# and solver/modflow6/extractors/sfr.py, lake.py (reach and lake series).
SIMULATED_SERIES: tuple[str, ...] = (
    "discharge",
    "well_pumping",
    "downstream_flow",
    "ext_inflow",
    "ext_outflow",
    "gw_exchange",
    "gwf_exchange",
    "to_mvr",
    "from_mvr",
    "runoff",
    "stage",
    "depth",
    "volume",
    "surface_area",
    "lake_bed_vertical_exchange",
    "rainfall",
    "evaporation",
    "inflow",
    "withdrawal",
    "storage",
    "outlet",
    "outlet_inflow",
    "cutoff_wall_flow",
)
"""Series a solve writes, named by variable."""

# The record variables of the observation families
# (data/variables/*/manager.py RECORD_VARIABLE and their API readers), stored
# with source = observed by data/ingest/observations.py.
OBSERVED_VARIABLES: tuple[str, ...] = (
    "discharge",
    "water_level",
    "groundwater_level",
    "groundwater_depth",
    "flow_state",
    "lake_level",
)
"""The variables an observation family records."""

OBSERVED_SERIES: tuple[str, ...] = tuple(series_name(name, OBSERVED) for name in OBSERVED_VARIABLES)
"""The names an export asks for an observed series by, stored beside the simulated ones."""

# catchment/preprocess/store_ingestion.py (watershed layers), workflow/steps/
# prepare_solver/forcings.py (reference networks), results/exporters/mesh_layers.py
# (the layers of the cell mesh).
VECTOR_LAYERS: tuple[str, ...] = (
    "watershed",
    "watershed_contour",
    "watershed_box_buff",
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    *MESH_LAYERS,
)
"""Vector layers a run holds: the geographic ones it stores and the layers of its cell mesh."""

# catchment/preprocess/store_ingestion.py (_RASTER_ATTRS).
RASTER_LAYERS: tuple[str, ...] = ("watershed_dem", "watershed_fill")
"""Geographic raster layers a run stores."""

TABLES: tuple[str, ...] = ("budget",)
"""Tables a run stores, written whole."""


def _field_names() -> list[str]:
    """Return the mesh fields, the virtual ones included."""
    return sorted(
        {*field_registry.all_names(), SIMULATED_ACTIVE_NETWORK, *MESH_QUALITY_DESCRIPTORS}
    )


def static_export_names() -> dict[str, ExportKind]:
    """Return every name some run can export, mapped to its kind.

    The order is the lookup order: a name two groups hold takes the kind of
    the first. Which of them a given run holds is known only on the run.
    """
    names: dict[str, ExportKind] = {}
    groups: tuple[tuple[ExportKind, list[str] | tuple[str, ...]], ...] = (
        (ExportKind.field, _field_names()),
        (ExportKind.series, SIMULATED_SERIES + OBSERVED_SERIES),
        (ExportKind.vector, VECTOR_LAYERS),
        (ExportKind.raster, RASTER_LAYERS),
        (ExportKind.table, TABLES),
    )
    for kind, group in groups:
        for name in group:
            names.setdefault(name, kind)
    return names


KIND_LABELS: dict[ExportKind, str] = {
    ExportKind.field: "fields",
    ExportKind.series: "series",
    ExportKind.vector: "vector layers",
    ExportKind.raster: "raster layers",
    ExportKind.table: "tables",
}
"""How a listing names each kind, in the lookup order."""


def export_kind(name: str) -> ExportKind | None:
    """Return the kind of an exportable name, or None when no run can hold it."""
    return static_export_names().get(name)


def describe_export_names() -> str:
    """Return the vocabulary as a message prints it, one line per kind."""
    by_kind: dict[ExportKind, list[str]] = {}
    for name, kind in static_export_names().items():
        by_kind.setdefault(kind, []).append(name)
    return "\n".join(
        f"  {label}: {', '.join(by_kind[kind])}"
        for kind, label in KIND_LABELS.items()
        if kind in by_kind
    )


def list_exportable(run: Run) -> dict[str, ExportKind]:
    """Return every name this run can export, mapped to its kind.

    The dynamic side of :func:`static_export_names`: what this run holds,
    read from its directory, never from the index. The fields are the
    registered ones the field store holds or rebuilds on read, plus the
    simulated stream network when the run carries what it is cut from, and
    the mesh quality fields its stored mesh can serve. The series are those of
    its ``timeseries`` table, a measurement named ``<variable>_obs``, the layers the files of its
    tables directory hold plus the mesh layers of a run that states its
    mesh CRS, and ``budget`` when its ``budgets`` table has rows. A name two
    groups hold takes the kind of the first, the order ``hmp.read``
    resolves a name in.
    """
    store = run._catalog
    sim_id = run.sim_id
    names: dict[str, ExportKind] = {}
    for name in run.array.list_fields():
        names.setdefault(name, ExportKind.field)
    for name in _mesh_quality_available(store, sim_id):
        names.setdefault(name, ExportKind.field)
    if network_unavailable_reason(run) is None:
        names.setdefault(SIMULATED_ACTIVE_NETWORK, ExportKind.field)
    for variable, source in distinct_rows(store, sim_id, TIMESERIES_TABLE, "variable", "source"):
        names.setdefault(series_name(variable, source), ExportKind.series)
    for feature in geographic_features(store, sim_id):
        names.setdefault(feature, ExportKind.vector)
    for layer in available_mesh_layers(store, sim_id):
        names.setdefault(layer, ExportKind.vector)
    for raster in _stored_rasters(store, sim_id):
        names.setdefault(raster, ExportKind.raster)
    if table_rows(store, sim_id, BUDGETS_TABLE):
        names.setdefault("budget", ExportKind.table)
    return names


def describe_exportable(names: dict[str, ExportKind]) -> str:
    """Return what one run can export as a listing prints it, one block per kind."""
    blocks: list[str] = []
    for kind, label in KIND_LABELS.items():
        held = sorted(name for name, name_kind in names.items() if name_kind is kind)
        if held:
            blocks.append(f"{label}:\n" + "\n".join(f"  {name}" for name in held))
    return "\n".join(blocks)


def _mesh_quality_available(store: Any, sim_id: str) -> list[str]:
    """Return the mesh quality fields the stored mesh of a run can serve."""
    sz = store.open_zarr(sim_id)
    try:
        served = set(available_virtual_fields(sz.root))
    finally:
        sz.close()
    return [name for name in MESH_QUALITY_DESCRIPTORS if name in served]


def network_unavailable_reason(run: Run) -> str | None:
    """Say why the run cannot cut its simulated stream network, or ``None`` when it can."""
    from hydromodpy.results.derive.stream.criterion_settings import network_criterion_settings
    from hydromodpy.results.derive.stream.run_extent import unavailable_reason_for_flow

    try:
        settings = network_criterion_settings(run)
        return unavailable_reason_for_flow(run, tau_specific_ratio=settings.tau_specific_ratio)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        return str(exc)


def _stored_rasters(store: Any, sim_id: str) -> list[str]:
    """Return the geographic rasters a run's field store holds.

    A raster carries its ``transform``. Its pixel-center axes and its
    grid-mapping variable sit beside it in the group and are not rasters.
    """
    sz = store.open_zarr(sim_id)
    try:
        group = sz.root.get("geographic")
        if group is None:
            return []
        return sorted(str(key) for key, array in group.arrays() if "transform" in array.attrs)
    finally:
        sz.close()


__all__ = [
    "KIND_LABELS",
    "OBSERVED_SERIES",
    "OBSERVED_VARIABLES",
    "RASTER_LAYERS",
    "SIMULATED_SERIES",
    "TABLES",
    "VECTOR_LAYERS",
    "describe_export_names",
    "describe_exportable",
    "export_kind",
    "list_exportable",
    "static_export_names",
]
