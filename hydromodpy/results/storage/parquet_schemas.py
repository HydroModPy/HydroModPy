"""PyArrow schemas for every per-simulation Parquet file.

One declared :class:`pa.Schema` per file under
``runs/<name>/tables.parquet/``: the appended views, and the two tables the
seal writes once (``simulation``, ``parameters``). These schemas are the single source of
truth for column names, Arrow types, nullability, primary keys, and field-level
metadata (units, descriptions, allowed values). The catalog write path casts
incoming records to the matching schema before handing them to
:func:`hydromodpy.results.storage.parquet_io.write_table_atomic`.

Schema-level metadata embeds ``hmp.schema``, ``hmp.schema_version``, ``hmp.pk``
and CF ``Conventions``. Per-field metadata documents the physical unit and a
short description. ``PARQUET_SCHEMA_VERSION`` is ``v2``. A table is read back with
:func:`~hydromodpy.results.storage.parquet_io.read_checked_table`, which refuses a
version outside :data:`PARQUET_VERSIONS`, for a read and for an append alike. A
column this code does not declare is additive: it reads, and an append keeps it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

import pyarrow as pa

from hydromodpy.core.io.document_version import VersionWindow, check_version

PARQUET_SCHEMA_VERSION: Final[str] = "v2"
"""Current Parquet schema generation. Stored in KV metadata of every file."""

PARQUET_VERSIONS: Final[VersionWindow] = VersionWindow(oldest="v2", current=PARQUET_SCHEMA_VERSION)
"""Versions of a table of a run this code reads."""

CF_CONVENTIONS: Final[str] = "CF-1.11"
"""CF convention version embedded in schema metadata."""


def _schema_metadata(
    name: str,
    *,
    pk: Iterable[str],
    extra: dict[str, str] | None = None,
) -> dict[bytes, bytes]:
    """Build the bytes-keyed metadata dict pyarrow expects on a schema."""
    payload: dict[str, str] = {
        "hmp.schema": name,
        "hmp.schema_version": PARQUET_SCHEMA_VERSION,
        "hmp.pk": ",".join(pk),
        "Conventions": CF_CONVENTIONS,
    }
    if extra:
        payload.update(extra)
    return {k.encode("utf-8"): v.encode("utf-8") for k, v in payload.items()}


def _field_meta(**kwargs: str) -> dict[bytes, bytes]:
    """Encode per-field metadata as bytes-keyed pairs."""
    return {k.encode("utf-8"): str(v).encode("utf-8") for k, v in kwargs.items()}


TIMESERIES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "station_id",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Observation station id, null for global series"),
        ),
        pa.field(
            "variable",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Physical variable name"),
        ),
        pa.field(
            "component",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Optional sub-component label"),
        ),
        pa.field(
            "timestep",
            pa.int64(),
            nullable=False,
            metadata=_field_meta(description="Integer time index, zero-based"),
        ),
        pa.field(
            "time",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Calendar time in UTC"),
        ),
        pa.field(
            "value",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Observed or simulated value"),
        ),
        pa.field(
            "unit",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="SI unit string"),
        ),
        pa.field(
            "qflag",
            pa.string(),
            nullable=True,
            metadata=_field_meta(
                allowed="simulated|observed|interpolated|filled",
                description="Quality flag for the data point",
            ),
        ),
    ],
    metadata=_schema_metadata(
        "timeseries",
        pk=("sim_id", "station_id", "variable", "timestep"),
    ),
)
"""Per-simulation timeseries observations and outputs."""


BUDGETS_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "timestep",
            pa.int64(),
            nullable=False,
            metadata=_field_meta(description="Integer time index"),
        ),
        pa.field(
            "zone_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Sub-domain identifier or __global__"),
        ),
        pa.field(
            "component",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Budget component name (e.g. recharge, drain)"),
        ),
        pa.field(
            "flux_in",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Inflow flux"),
        ),
        pa.field(
            "flux_out",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Outflow flux"),
        ),
        pa.field(
            "unit",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Flux unit"),
        ),
    ],
    metadata=_schema_metadata(
        "budgets",
        pk=("sim_id", "timestep", "zone_id", "component"),
    ),
)
"""Per-simulation water budget per zone and component."""


MASS_BALANCE_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "timestep",
            pa.int64(),
            nullable=False,
            metadata=_field_meta(description="Integer time index"),
        ),
        pa.field(
            "quantity",
            pa.string(),
            nullable=False,
            metadata=_field_meta(
                description="Balanced quantity: 'water' (GWF volume budget) or "
                "'solute' (GWT mass budget)"
            ),
        ),
        pa.field(
            "total_in",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Total inflow; per-row unit in the 'unit' column "
                "(m3/s for water, mass/s for solute)"
            ),
        ),
        pa.field(
            "total_out",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Total outflow; per-row unit in the 'unit' column "
                "(m3/s for water, mass/s for solute)"
            ),
        ),
        pa.field(
            "storage_in",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Storage gain; per-row unit in the 'unit' column. "
                "Left 0.0 for solute (GWT STORAGE-AQUEOUS not split out)"
            ),
        ),
        pa.field(
            "storage_out",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Storage loss; per-row unit in the 'unit' column. "
                "Left 0.0 for solute (GWT STORAGE-AQUEOUS not split out)"
            ),
        ),
        pa.field(
            "percent_error",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                unit="percent",
                description="Mass balance residual, expressed in percent",
            ),
        ),
        pa.field(
            "unit",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Flux unit for *_in and *_out columns"),
        ),
    ],
    metadata=_schema_metadata(
        "mass_balance",
        pk=("sim_id", "timestep", "quantity"),
    ),
)
"""Per-simulation global mass balance summary (water and solute budgets)."""


METRICS_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "station_id",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Station the metric refers to, when applicable"),
        ),
        pa.field(
            "variable",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Variable the metric refers to"),
        ),
        pa.field(
            "metric",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Metric name (NSE, KGE, RMSE, ...)"),
        ),
        pa.field(
            "value",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Numerical metric value"),
        ),
        pa.field(
            "n_samples",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(description="Number of samples used"),
        ),
        pa.field(
            "n_clipped",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(
                description="Negative values clipped to zero before a log-scale score; "
                "null on a metric that never clips"
            ),
        ),
        pa.field(
            "n_sim_nan",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(
                description="Periods of the window dropped because the simulated value is "
                "NaN (a dry cell); null when not counted"
            ),
        ),
        pa.field(
            "valid_from",
            pa.timestamp("ms", tz="UTC"),
            nullable=False,
            metadata=_field_meta(description="Validity start, UTC"),
        ),
        pa.field(
            "period_start",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Window start of the evaluation"),
        ),
        pa.field(
            "period_end",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Window end of the evaluation"),
        ),
    ],
    metadata=_schema_metadata(
        "metrics",
        pk=("sim_id", "station_id", "variable", "metric"),
    ),
)
"""Per-simulation calibration and validation metrics."""


PARAMETERS_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "param_name",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Parameter name as the solver builder knows it"),
        ),
        pa.field(
            "zone_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Zone the value applies to, or __global__"),
        ),
        pa.field(
            "value",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(description="Numerical parameter value"),
        ),
        pa.field(
            "unit",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Physical unit of the value"),
        ),
        pa.field(
            "parameterization",
            pa.string(),
            nullable=True,
            metadata=_field_meta(
                description="How the value was obtained (uniform, zonal, calibrated, ...)"
            ),
        ),
        pa.field(
            "valid_from",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Timestamp the value became current, UTC"),
        ),
        pa.field(
            "origin",
            pa.string(),
            nullable=False,
            metadata=_field_meta(
                allowed="declared|site_table|site_override|recipe|calibrated",
                description="Where the value came from: the file, the site table, a site "
                "override, the recipe, or the calibration that promoted this run",
            ),
        ),
        pa.field(
            "calibrated",
            pa.bool_(),
            nullable=False,
            metadata=_field_meta(description="True when a calibration set the value"),
        ),
    ],
    metadata=_schema_metadata(
        "parameters",
        pk=("sim_id", "param_name", "zone_id"),
    ),
)
"""Per-run parameter values, one row per parameter and present zone.

Written once at seal time from the :class:`~hydromodpy.results.record.RunRecord`,
not appended to during the run, so it is not a Parquet *view*: it stays out of
:data:`VIEW_SCHEMAS` and of ``PARQUET_VIEW_NAMES``.
"""


def _checks_fields() -> list[pa.Field]:
    """The flattened ``checks`` block of the seal, one column per fact."""
    return [
        pa.field(
            "budget_pct",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="percent", description="Water-budget discrepancy"),
        ),
        pa.field(
            "budget_threshold_pct",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="percent", description="Discrepancy the user accepts"),
        ),
        pa.field(
            "converged",
            pa.bool_(),
            nullable=True,
            metadata=_field_meta(description="Solver convergence reported by the backend"),
        ),
        pa.field(
            "obs_coverage",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(description="Share of the score window covered by observations"),
        ),
        pa.field(
            "score_window_start",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="First day of the window the run was scored on"),
        ),
        pa.field(
            "score_window_end",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="Last day of the window the run was scored on"),
        ),
        pa.field(
            "n_samples",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(description="Samples the score used"),
        ),
        pa.field(
            "calibrated_by_session_id",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Session that promoted this run"),
        ),
        pa.field(
            "calibrated_by_phase",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Phase of that session"),
        ),
        pa.field(
            "calibrated_by_trial",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(description="Trial of that session"),
        ),
        pa.field(
            "calibrated_by_session_status",
            pa.string(),
            nullable=True,
            metadata=_field_meta(
                allowed="completed|partial|aborted",
                description="How that session ended",
            ),
        ),
        pa.field(
            "calibrated_by_window_start",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="First day of the window that session scored"),
        ),
        pa.field(
            "calibrated_by_window_end",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="Last day of the window that session scored"),
        ),
        pa.field(
            "validities_failed",
            pa.string(),
            nullable=True,
            metadata=_field_meta(
                description="Names of the validities that failed, comma separated; null when none"
            ),
        ),
        pa.field(
            "fatal_failed",
            pa.bool_(),
            nullable=False,
            metadata=_field_meta(description="True when a fatal validity failed"),
        ),
        pa.field(
            "bounds_hit",
            pa.string(),
            nullable=True,
            metadata=_field_meta(
                description="Calibrated parameters that sit on a bound, comma separated; null when none"
            ),
        ),
        pa.field(
            "code_reproducible",
            pa.bool_(),
            nullable=True,
            metadata=_field_meta(description="False for a dirty checkout or an editable install"),
        ),
    ]


CHECK_COLUMNS: Final[tuple[str, ...]] = tuple(field.name for field in _checks_fields())
"""Column names of the flattened ``checks`` block, in order."""


SIMULATION_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "name",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Run name, with its .vN"),
        ),
        pa.field("name_stem", pa.string(), nullable=False),
        pa.field("version_int", pa.int32(), nullable=False),
        pa.field("project", pa.string(), nullable=False),
        pa.field("site", pa.string(), nullable=True, metadata=_field_meta(description="Site name")),
        pa.field("site_fingerprint", pa.string(), nullable=True),
        pa.field(
            "recipe",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Recipe of a planned case"),
        ),
        pa.field("case_id", pa.string(), nullable=False),
        pa.field(
            "rel_dir",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Run directory, relative to the project root"),
        ),
        pa.field("attempt", pa.int32(), nullable=False),
        pa.field("attempt_id", pa.string(), nullable=False),
        pa.field("solver", pa.string(), nullable=False),
        pa.field("solver_category", pa.string(), nullable=True),
        pa.field(
            "status",
            pa.string(),
            nullable=False,
            metadata=_field_meta(
                allowed="completed",
                description="Always completed: only a completed run is sealed",
            ),
        ),
        pa.field("flow_regime", pa.string(), nullable=True),
        pa.field("mesh_topology", pa.string(), nullable=True),
        pa.field("mesh_hash", pa.string(), nullable=True),
        pa.field("n_cells", pa.int64(), nullable=True),
        pa.field("n_layers", pa.int32(), nullable=True),
        pa.field("n_timesteps", pa.int64(), nullable=True),
        pa.field("crs_wkt", pa.string(), nullable=True),
        pa.field("crs_epsg", pa.int32(), nullable=True),
        pa.field("bbox_xmin", pa.float64(), nullable=True),
        pa.field("bbox_ymin", pa.float64(), nullable=True),
        pa.field("bbox_xmax", pa.float64(), nullable=True),
        pa.field("bbox_ymax", pa.float64(), nullable=True),
        pa.field("period_start", pa.timestamp("ms", tz="UTC"), nullable=True),
        pa.field("period_end", pa.timestamp("ms", tz="UTC"), nullable=True),
        pa.field("time_unit", pa.string(), nullable=True),
        pa.field("config_hash", pa.string(), nullable=True),
        pa.field("config_source", pa.string(), nullable=True),
        pa.field("parent_sim_id", pa.string(), nullable=True),
        pa.field(
            "lineage_kind",
            pa.string(),
            nullable=True,
            metadata=_field_meta(allowed="rerun|promoted|trial|version"),
        ),
        pa.field("session_id", pa.string(), nullable=True),
        pa.field("hydromodpy_version", pa.string(), nullable=False),
        pa.field("created_at", pa.timestamp("ms", tz="UTC"), nullable=False),
        pa.field("started_at", pa.timestamp("ms", tz="UTC"), nullable=True),
        pa.field("ended_at", pa.timestamp("ms", tz="UTC"), nullable=True),
        pa.field("duration_s", pa.float64(), nullable=True),
        pa.field("description", pa.string(), nullable=True),
        pa.field("scientific_objective", pa.string(), nullable=True),
        pa.field("contact_email", pa.string(), nullable=True),
        pa.field("doi", pa.string(), nullable=True),
        *_checks_fields(),
        pa.field(
            "nse",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="NSE at the declared station over the declared window; null without a window"
            ),
        ),
        pa.field(
            "nse_station",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Station the NSE was read at"),
        ),
        pa.field(
            "nse_variable",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Variable the NSE was read on"),
        ),
        pa.field("nse_window_start", pa.date32(), nullable=True),
        pa.field("nse_window_end", pa.date32(), nullable=True),
        pa.field("nse_n", pa.int64(), nullable=True),
        pa.field("metric_rule_version", pa.string(), nullable=True),
        pa.field(
            "objective_name",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Objective of the session that promoted the run"),
        ),
        pa.field(
            "objective_value",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(description="Value of that objective for this run"),
        ),
        pa.field(
            "objective_window_start",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="First day the session scored the objective on"),
        ),
        pa.field(
            "objective_window_end",
            pa.date32(),
            nullable=True,
            metadata=_field_meta(description="Last day the session scored the objective on"),
        ),
    ],
    metadata=_schema_metadata("simulation", pk=("sim_id",)),
)
"""The one-row index payload of a run, written at seal time from its ``RunRecord``.

What the ``simulations`` index table holds about a run and means outside SQL,
plus the site, the case, the attempt, the flattened ``checks``, the headline
metric under its rule and the objective of the promoting session. Written
for a completed run only: ``status`` is always ``completed``. The site
fingerprint is ``site_fingerprint``, the only one. No label: the label is a function of reading. Not a
Parquet *view* either: one file per run, read back whole by the indexer.
"""


PROVENANCE_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "variable",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Variable name the record describes"),
        ),
        pa.field(
            "source_type",
            pa.string(),
            nullable=False,
            metadata=_field_meta(
                allowed="http_api|custom_file|data_manager|derived|cache",
                description="Source category",
            ),
        ),
        pa.field(
            "source_ref",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Free-form reference (URL or path)"),
        ),
        pa.field(
            "source_sha256",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="SHA-256 of the source artefact, hex digest"),
        ),
        pa.field(
            "loader_name",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Loader implementation identifier"),
        ),
        pa.field(
            "loader_version",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Loader semantic version"),
        ),
        pa.field(
            "fetched_at",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Fetch timestamp, UTC"),
        ),
        pa.field(
            "period_start",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Time coverage start"),
        ),
        pa.field(
            "period_end",
            pa.timestamp("ms", tz="UTC"),
            nullable=True,
            metadata=_field_meta(description="Time coverage end"),
        ),
        pa.field(
            "payload_sha256",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="SHA-256 of the materialised array payload"),
        ),
        pa.field(
            "n_records",
            pa.int64(),
            nullable=True,
            metadata=_field_meta(description="Cardinality of the materialised payload"),
        ),
        pa.field(
            "stats",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="JSON-encoded summary statistics"),
        ),
    ],
    metadata=_schema_metadata(
        "provenance",
        pk=("sim_id", "variable", "source_ref"),
    ),
)
"""Per-simulation provenance records for inputs and derived arrays."""


OBSERVATION_POINTS_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "station_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Id of the declared observation point"),
        ),
        pa.field(
            "x",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Easting in the simulation CRS"),
        ),
        pa.field(
            "y",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Northing in the simulation CRS"),
        ),
        pa.field(
            "cell_id",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Zero-based mesh cell holding the point"),
        ),
        pa.field(
            "layer",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Zero-based layer the point is read in"),
        ),
        pa.field(
            "crs_wkt",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="CRS of x and y, as WKT or an authority code"),
        ),
        pa.field(
            "crs_epsg",
            pa.int32(),
            nullable=True,
            metadata=_field_meta(description="EPSG code of the CRS when known"),
        ),
    ],
    metadata=_schema_metadata(
        "observation_points",
        pk=("sim_id", "station_id"),
    ),
)
"""Per-run declared observation points: where the model was probed.

The run directory is the only home of this declaration. Exposing it as a
Parquet *view* rather than as an index table is what makes it survive
``hmp catalog reindex``: the view globs the run directories, so a rebuilt
index finds the points again with the files themselves.
"""


SFR_REACHES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "network_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Id of the SFR network the reach belongs to"),
        ),
        pa.field(
            "ifno",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Zero-based reach number, increasing downstream"),
        ),
        pa.field(
            "cell2d",
            pa.int32(),
            nullable=True,
            metadata=_field_meta(description="Mesh cell carrying the reach; null when unconnected"),
        ),
        pa.field(
            "layer",
            pa.int32(),
            nullable=True,
            metadata=_field_meta(description="Zero-based layer the reach exchanges with"),
        ),
        pa.field(
            "rtp",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Streambed top elevation, model length units"),
        ),
        pa.field(
            "rbth",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Streambed thickness; MODFLOW switches connection at rtp - rbth"
            ),
        ),
        pa.field(
            "rlen",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Reach length inside its cell"),
        ),
        pa.field(
            "rwid",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Reach width"),
        ),
        pa.field(
            "rgrd",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Reach gradient, dimensionless"),
        ),
        pa.field(
            "rhk",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Streambed hydraulic conductivity, m/s"),
        ),
        pa.field(
            "manning",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Manning roughness of the reach"),
        ),
        pa.field(
            "strahler",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Strahler order read at the link outlet"),
        ),
        pa.field(
            "ustrf",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Fraction of upstream flow routed into the reach"),
        ),
        pa.field(
            "downstream",
            pa.list_(pa.int32()),
            nullable=False,
            metadata=_field_meta(
                description="Reach numbers this reach drains into; empty at an outlet"
            ),
        ),
    ],
    metadata=_schema_metadata(
        "sfr_reaches",
        pk=("sim_id", "network_id", "ifno"),
    ),
)
"""Resolved geometry of every SFR reach, as written into the MODFLOW package.

The MODFLOW input files are scratch, so without this table a sealed run cannot
say which cell carries which reach, at what bed elevation, nor where the
connection threshold ``rtp - rbth`` sits. Every figure that wants to draw the
streambed reads it here.
"""

SOIL_BUDGET_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "column_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(
                description=(
                    'Soil column as "<cell_index>.<class_index>", or "_watershed" '
                    "for the basin mean"
                )
            ),
        ),
        pa.field(
            "cell_index",
            pa.int32(),
            nullable=True,
            metadata=_field_meta(
                description="Flat (y, x) index of the SAFRAN cell; null on the basin row"
            ),
        ),
        pa.field(
            "class_index",
            pa.int32(),
            nullable=True,
            metadata=_field_meta(
                description="Soil capacity class inside the cell; null on the basin row"
            ),
        ),
        pa.field(
            "x",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Cell centre x, CRS of the run; null on the basin row"
            ),
        ),
        pa.field(
            "y",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Cell centre y, CRS of the run; null on the basin row"
            ),
        ),
        pa.field(
            "ru_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Soil available water capacity, mm; weighted mean on the basin row"
            ),
        ),
        pa.field(
            "basin_weight",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Weight of the column in the basin row; 1 on the basin row"
            ),
        ),
        pa.field(
            "year", pa.int32(), nullable=False, metadata=_field_meta(description="Calendar year")
        ),
        pa.field(
            "days",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(
                description="Days of that year inside the run; below 365 for a partial year"
            ),
        ),
        pa.field(
            "precipitation_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Precipitation, mm over the days of the row"),
        ),
        pa.field(
            "etp_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="ETP as loaded, before kc, mm"),
        ),
        pa.field(
            "etr_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Actual evapotranspiration of the soil, mm"),
        ),
        pa.field(
            "residual_etp_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="ETP the soil left unmet, mm"),
        ),
        pa.field(
            "recharge_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Recharge sent to the water table, mm"),
        ),
        pa.field(
            "runoff_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Runoff of the sealed share plus the routed curve-number share, mm"
            ),
        ),
        pa.field(
            "runoff_cn_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Curve-number share of runoff alone, mm; 0 when curve_number is off"
            ),
        ),
        pa.field(
            "soil_storage_change_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Change of the soil storage over the row, mm"),
        ),
        pa.field(
            "transit_storage_change_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(description="Change of the transit store over the row, mm"),
        ),
        pa.field(
            "cn_storage_change_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Change of the curve-number routing store over the row, mm; "
                "0 when curve_number is off"
            ),
        ),
        pa.field(
            "lag_storage_change_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="Change of the runoff_lag delay line over the row, mm; "
                "0 when runoff_lag is 0"
            ),
        ),
        pa.field(
            "balance_residual_mm",
            pa.float64(),
            nullable=False,
            metadata=_field_meta(
                description="P - ETR - recharge - runoff - storage changes, mm; zero to machine precision"
            ),
        ),
    ],
    metadata=_schema_metadata(
        "soil_budget",
        pk=("sim_id", "column_id", "year"),
    ),
)
"""Annual soil-reservoir budget, one row per column and calendar year.

A ``_watershed`` row per year sums the columns weighted by ``basin_weight``,
the same aggregation the printed water-budget block uses. Absent outside soil
mode.
"""


MESH_CELL_FAMILIES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "family",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Name of the cell family, e.g. rivers"),
        ),
        pa.field(
            "chain_id",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Id of the chain inside its family"),
        ),
        pa.field(
            "position",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Rank of the cell along the chain, 0 upstream"),
        ),
        pa.field(
            "cell_id",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Cell, as its rank on the face axis of the fields"),
        ),
        pa.field(
            "offset_m",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(
                description="Distance from the cell centre to the family line, m; null when the chain gives none"
            ),
        ),
    ],
    metadata=_schema_metadata(
        "mesh_cell_families",
        pk=("sim_id", "family", "chain_id", "position"),
    ),
)
"""Ordered cells of every cell-intent family of the mesh (the rasterized river).

The ``mesh/face_family`` bit field says which cells belong to a family; this table
keeps the order along the line, which a bit field cannot. Absent when the mesh has
no cell chain.
"""

MESH_FACE_FAMILIES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("sim_id", pa.string(), nullable=False),
        pa.field(
            "face_row",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Row of the face in the mesh family table"),
        ),
        pa.field(
            "family",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Name of the face family, e.g. rivers"),
        ),
        pa.field(
            "edge_id",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Rank of the face in the mesh/edge_* arrays"),
        ),
        pa.field(
            "node_a",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="First vertex of the face"),
        ),
        pa.field(
            "node_b",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Second vertex of the face"),
        ),
        pa.field(
            "cell_a",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(description="Cell on the left of the oriented family line"),
        ),
        pa.field(
            "cell_b",
            pa.int32(),
            nullable=False,
            metadata=_field_meta(
                description="Cell on the right of the oriented family line, -1 on the boundary"
            ),
        ),
        pa.field(
            "zone_left",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Zone on the left of the line; null when unknown"),
        ),
        pa.field(
            "zone_right",
            pa.string(),
            nullable=True,
            metadata=_field_meta(description="Zone on the right of the line; null when unknown"),
        ),
    ],
    metadata=_schema_metadata(
        "mesh_face_families",
        pk=("sim_id", "face_row"),
    ),
)
"""Every mesh face that lies on a face-intent family line (lakes, geology, boundaries).

A table absent from a run that stored its mesh in the cell-mesh layout means the
mesh has no such face; a run sealed before that layout has neither table nor the
``engine`` attribute on ``mesh/``.
"""


# Geographic vector files are NOT declared as a pa.Schema here: they are written
# by ``geopandas.to_parquet`` (OGC GeoParquet 1.1) and carry every column of the
# source GeoDataFrame plus the ``geo`` OGC metadata key, so no fixed pyarrow
# schema describes them faithfully. Consumers should read them with
# ``geopandas.read_parquet`` and expect at least a ``geometry`` column (WKB) plus
# the attributes the producing step attached; they are keyed logically by
# ``(sim_id, feature_name)`` via the ``geographic_features`` catalog table.


VIEW_SCHEMAS: Final[dict[str, pa.Schema]] = {
    "timeseries": TIMESERIES_SCHEMA,
    "budgets": BUDGETS_SCHEMA,
    "mass_balance": MASS_BALANCE_SCHEMA,
    "metrics": METRICS_SCHEMA,
    "provenance": PROVENANCE_SCHEMA,
    "observation_points": OBSERVATION_POINTS_SCHEMA,
    "sfr_reaches": SFR_REACHES_SCHEMA,
    "soil_budget": SOIL_BUDGET_SCHEMA,
    "mesh_cell_families": MESH_CELL_FAMILIES_SCHEMA,
    "mesh_face_families": MESH_FACE_FAMILIES_SCHEMA,
}
"""Map of per-simulation view name to declared :class:`pa.Schema`."""


def schema_for(view_name: str) -> pa.Schema:
    """Return the declared :class:`pa.Schema` for ``view_name``."""
    try:
        return VIEW_SCHEMAS[view_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Parquet view: {view_name!r}") from exc


def primary_key_for(view_name: str) -> tuple[str, ...]:
    """Return the declared primary key of ``view_name``, from its schema metadata."""
    metadata = schema_for(view_name).metadata or {}
    raw = metadata.get(b"hmp.pk")
    if raw is None:
        raise KeyError(f"Parquet view {view_name!r} declares no primary key")
    return tuple(raw.decode("utf-8").split(","))


def check_schema_version(metadata: dict[bytes, bytes] | None, *, document: object) -> None:
    """Refuse a table of a run whose ``hmp.schema_version`` lies outside the window.

    *metadata* is the schema metadata pyarrow returns, *document* names the file.
    """
    found = (metadata or {}).get(b"hmp.schema_version")
    writer = (metadata or {}).get(b"hydromodpy_version")
    check_version(
        None if found is None else found.decode("utf-8"),
        PARQUET_VERSIONS,
        document=str(document),
        key="hmp.schema_version",
        writer=None if writer is None else writer.decode("utf-8"),
    )


__all__ = [
    "BUDGETS_SCHEMA",
    "CF_CONVENTIONS",
    "CHECK_COLUMNS",
    "MASS_BALANCE_SCHEMA",
    "MESH_CELL_FAMILIES_SCHEMA",
    "MESH_FACE_FAMILIES_SCHEMA",
    "METRICS_SCHEMA",
    "OBSERVATION_POINTS_SCHEMA",
    "PARAMETERS_SCHEMA",
    "PARQUET_SCHEMA_VERSION",
    "PARQUET_VERSIONS",
    "PROVENANCE_SCHEMA",
    "TIMESERIES_SCHEMA",
    "SFR_REACHES_SCHEMA",
    "SIMULATION_SCHEMA",
    "SOIL_BUDGET_SCHEMA",
    "VIEW_SCHEMAS",
    "check_schema_version",
    "primary_key_for",
    "schema_for",
]
