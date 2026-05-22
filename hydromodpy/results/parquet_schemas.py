"""PyArrow schemas for every per-simulation Parquet view.

One declared :class:`pa.Schema` per file under
``simulations/<basename>.parquet/``. These schemas are the single source of
truth for column names, Arrow types, nullability, primary keys, and field-level
metadata (units, descriptions, allowed values). The catalog write path casts
incoming records to the matching schema before handing them to
:func:`hydromodpy.results.parquet_io.write_table_atomic`.

Schema-level metadata embeds ``hmp.schema``, ``hmp.schema_version``, ``hmp.pk``
and CF ``Conventions``. Per-field metadata documents the physical unit and a
short description. ``PARQUET_SCHEMA_VERSION`` is bumped to ``v2`` and rejected
at read time when a Parquet file ships an older marker.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

import pyarrow as pa

PARQUET_SCHEMA_VERSION: Final[str] = "v2"
"""Current Parquet schema generation. Stored in KV metadata of every file."""

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
            "total_in",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Total inflow"),
        ),
        pa.field(
            "total_out",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Total outflow"),
        ),
        pa.field(
            "storage_in",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Storage gain"),
        ),
        pa.field(
            "storage_out",
            pa.float64(),
            nullable=True,
            metadata=_field_meta(unit="m3/s", description="Storage loss"),
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
        pk=("sim_id", "timestep"),
    ),
)
"""Per-simulation global mass balance summary."""


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


GEOGRAPHIC_FEATURES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field(
            "sim_id",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Owning simulation id"),
        ),
        pa.field(
            "feature_name",
            pa.string(),
            nullable=False,
            metadata=_field_meta(description="Feature collection name"),
        ),
        pa.field(
            "geometry",
            pa.binary(),
            nullable=False,
            metadata=_field_meta(
                encoding="WKB",
                description="Well-Known Binary encoded geometry",
            ),
        ),
    ],
    metadata=_schema_metadata(
        "geographic_features",
        pk=("sim_id", "feature_name"),
        extra={"geometry_encoding": "WKB"},
    ),
)
"""Logical schema of the GeoParquet 1.1 vector files.

Note: in practice the on-disk file is produced by ``geopandas.to_parquet``
which adds extra columns inherited from the source ``GeoDataFrame`` plus the
``geo`` OGC metadata key. This schema is the minimum contract every consumer
should expect.
"""


VIEW_SCHEMAS: Final[dict[str, pa.Schema]] = {
    "timeseries": TIMESERIES_SCHEMA,
    "budgets": BUDGETS_SCHEMA,
    "mass_balance": MASS_BALANCE_SCHEMA,
    "metrics": METRICS_SCHEMA,
    "provenance": PROVENANCE_SCHEMA,
}
"""Map of per-simulation view name to declared :class:`pa.Schema`."""


class ParquetSchemaVersionError(ValueError):
    """Raised when a Parquet file ships an unsupported ``hmp.schema_version``."""


def schema_for(view_name: str) -> pa.Schema:
    """Return the declared :class:`pa.Schema` for ``view_name``."""
    try:
        return VIEW_SCHEMAS[view_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Parquet view: {view_name!r}") from exc


def check_schema_version(metadata: dict[bytes, bytes] | dict[str, str] | None) -> None:
    """Raise :class:`ParquetSchemaVersionError` if ``hmp.schema_version`` differs.

    A missing version is also rejected: a file that pre-dates the v2 contract
    must be migrated first. Strings keys and byte keys are both accepted to
    accept both raw pyarrow metadata dicts and decoded ones.
    """
    if not metadata:
        raise ParquetSchemaVersionError(
            "No HMP metadata found on Parquet file; expected schema_version "
            f"{PARQUET_SCHEMA_VERSION!r}"
        )
    found: str | None = None
    for key, raw in metadata.items():
        key_text = key.decode("utf-8") if isinstance(key, bytes) else key
        if key_text == "hmp.schema_version":
            found = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            break
    if found is None:
        raise ParquetSchemaVersionError(
            f"Missing hmp.schema_version in Parquet metadata; expected {PARQUET_SCHEMA_VERSION!r}"
        )
    if found != PARQUET_SCHEMA_VERSION:
        raise ParquetSchemaVersionError(
            f"Parquet schema_version {found!r} does not match expected {PARQUET_SCHEMA_VERSION!r}"
        )


__all__ = [
    "BUDGETS_SCHEMA",
    "CF_CONVENTIONS",
    "GEOGRAPHIC_FEATURES_SCHEMA",
    "MASS_BALANCE_SCHEMA",
    "METRICS_SCHEMA",
    "PARQUET_SCHEMA_VERSION",
    "PROVENANCE_SCHEMA",
    "ParquetSchemaVersionError",
    "TIMESERIES_SCHEMA",
    "VIEW_SCHEMAS",
    "check_schema_version",
    "schema_for",
]
