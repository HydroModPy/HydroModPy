"""The names a user can export, and the kind of each.

``[[export]] variables``, ``run.export`` and ``hmp export`` read one namespace.
It holds the mesh fields, the series, the vector layers, the raster layers and
the tables a run can store. The kind of a name decides its natural format and
the formats it can be written in
(:data:`~hydromodpy.core.config_kit.export_spec.KIND_FORMATS`).

This module holds the static part: every name some run can hold, known before
any run exists. The step 0 check reads it to refuse a typo before the solve.
A name is looked up in the order ``hmp.read`` resolves it: the field registry
first, then the series, the vector layers, the raster layers and the tables.

The names are the stored ones. The series and layer names are written by
layers ``results`` may not import (``simulation``, ``solver``, ``data``), so
they are restated here; each group names the module that writes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.config_kit.export_spec import ExportKind
from hydromodpy.results import field_registry
from hydromodpy.results.derive.snapped_network import SNAPPED_NETWORK_FEATURES
from hydromodpy.results.derive.virtual_fields import SIMULATED_ACTIVE_NETWORK
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
)

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

# simulation/extraction/derivation/catchment_aggregation.py (catchment series)
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
    "seepage_under_dam",
    "rainfall",
    "evaporation",
    "inflow",
    "withdrawal",
    "storage",
    "outlet",
)
"""Series a solve writes, named by variable."""

# The record variables of the observation families
# (data/variables/*/manager.py RECORD_VARIABLE and their API readers),
# stored as <variable>_obs by simulation/extraction/derivation/observation_ingest.py.
OBSERVED_VARIABLES: tuple[str, ...] = (
    "discharge",
    "water_level",
    "groundwater_level",
    "groundwater_depth",
    "flow_state",
    "lake_level",
)
"""The variables an observation family records."""

OBSERVED_SERIES: tuple[str, ...] = tuple(f"{name}_obs" for name in OBSERVED_VARIABLES)
"""Observed series, stored beside the simulated ones."""

# spatial/geographic/store_ingestion.py (watershed layers), workflow/steps/
# prepare_solver/prepare.py (reference networks), results/derive/snapped_network.py.
VECTOR_LAYERS: tuple[str, ...] = (
    "watershed",
    "watershed_contour",
    "watershed_box_buff",
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    *SNAPPED_NETWORK_FEATURES.values(),
)
"""Geographic vector layers a run stores."""

# spatial/geographic/store_ingestion.py (_RASTER_ATTRS).
RASTER_LAYERS: tuple[str, ...] = ("watershed_dem", "watershed_fill")
"""Geographic raster layers a run stores."""

TABLES: tuple[str, ...] = ("budget",)
"""Tables a run stores, written whole."""


def _field_names() -> list[str]:
    """Return the mesh fields, the virtual ones included."""
    return sorted({*field_registry.all_names(), SIMULATED_ACTIVE_NETWORK})


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


def export_kind(name: str) -> ExportKind | None:
    """Return the kind of an exportable name, or None when no run can hold it."""
    return static_export_names().get(name)


def describe_export_names() -> str:
    """Return the vocabulary as a message prints it, one line per kind."""
    by_kind: dict[ExportKind, list[str]] = {}
    for name, kind in static_export_names().items():
        by_kind.setdefault(kind, []).append(name)
    labels = {
        ExportKind.field: "fields",
        ExportKind.series: "series",
        ExportKind.vector: "vector layers",
        ExportKind.raster: "raster layers",
        ExportKind.table: "tables",
    }
    return "\n".join(
        f"  {labels[kind]}: {', '.join(by_kind[kind])}" for kind in labels if kind in by_kind
    )


KIND_LABELS: dict[ExportKind, str] = {
    ExportKind.field: "fields",
    ExportKind.series: "series",
    ExportKind.vector: "vector layers",
    ExportKind.raster: "raster layers",
    ExportKind.table: "tables",
}
"""How a listing names each kind, in the lookup order."""


def list_exportable(run: Run) -> dict[str, ExportKind]:
    """Return every name this run can export, mapped to its kind.

    The dynamic side of :func:`static_export_names`: what this run holds, read
    from its store and its catalog rows. The fields are the registered ones
    the store holds or rebuilds on read, plus the simulated stream network
    when the run carries what it is cut from. The series are the variables of
    its ``timeseries`` rows, the layers what its geographic store holds, and
    ``budget`` when it wrote budget rows. A name two groups hold takes the kind
    of the first, the order ``hmp.read`` resolves a name in.
    """
    catalog = run._catalog
    sim_id = run.sim_id
    names: dict[str, ExportKind] = {}
    for name in run.array.list_fields():
        names.setdefault(name, ExportKind.field)
    if _simulated_network_available(run):
        names.setdefault(SIMULATED_ACTIVE_NETWORK, ExportKind.field)
    for (variable,) in catalog.backend.fetch_all(
        "SELECT DISTINCT variable FROM timeseries WHERE sim_id = ? ORDER BY variable", [sim_id]
    ):
        names.setdefault(str(variable), ExportKind.series)
    for feature in catalog.list_geographic_features(sim_id):
        names.setdefault(str(feature), ExportKind.vector)
    for raster in _stored_rasters(catalog, sim_id):
        names.setdefault(raster, ExportKind.raster)
    budget_row = catalog.backend.fetch_one(
        "SELECT 1 FROM budgets WHERE sim_id = ? LIMIT 1", [sim_id]
    )
    if budget_row is not None:
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


def _simulated_network_available(run: Run) -> bool:
    """Return whether the run carries what its simulated stream network is cut from."""
    from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
    from hydromodpy.results.derive.stream_extent import unavailable_reason_for_flow

    try:
        settings = network_criterion_settings(run)
        reason = unavailable_reason_for_flow(run, tau_specific_ratio=settings.tau_specific_ratio)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError):
        return False
    return reason is None


def _stored_rasters(catalog: object, sim_id: str) -> list[str]:
    """Return the geographic rasters a run's field store holds."""
    store = catalog.open_zarr(sim_id)  # type: ignore[attr-defined]
    try:
        group = store.root.get("geographic")
        return sorted(str(key) for key in group.keys()) if group is not None else []
    finally:
        store.close()


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
