"""Single-switch persistence configuration (Principe 8).

``PersistenceConfig`` is the orthogonal save/no-save knob shared by every
write path: the DuckDB Catalog and the per-run Zarr and Parquet artifacts.
It also says how precisely the Zarr store keeps its time-varying fields.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.field_precision import DEFAULT_FIELD_PRECISION, FieldPrecision

CompressionCodec = Literal["none", "zstd", "lz4", "gzip", "snappy"]


class PersistenceConfig(HydroModelBase):
    """Orthogonal switch governing every persistence sink.

    Toggles are independent: disabling ``save_zarr`` does not silence the
    catalog, and vice versa. ``save_catalog`` is the master switch for the
    project DuckDB; when False, every write through
    :class:`Catalog` becomes a no-op.
    """

    save_catalog: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Persist DuckDB rows (simulations, parameters, metrics, "
        "calibration_iterations). When False, catalog writes are skipped.",
    )
    save_zarr: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Persist per-simulation field arrays (head, concentration, "
        "derived) into the Zarr store.",
    )
    field_precision: Annotated[FieldPrecision, Profile.USER] = Field(
        default=DEFAULT_FIELD_PRECISION,
        description=(
            "Precision of the time-varying field arrays of fields.zarr: heads, per-cell "
            "budget terms, derived fields, concentrations. 'compact' stores float32 with "
            "the mantissa rounded to nearest at 16 bits: each value moves by at most "
            "2**-17 of itself (7.6e-6 relative, so at most 1 mm on a 130 m head and "
            "7.6e-9 m3/s on a 1e-3 m3/s cell flux), and a daily run takes about a "
            "third of the disk. 'exact' keeps every value as computed, float64. "
            "Mesh geometry, topography, layer thickness, indices, coordinates and "
            "timestamps are never rounded."
        ),
    )
    save_parquet: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Persist per-simulation tabular outputs (timeseries, "
        "budgets, mass_balance) as Parquet files.",
    )
    compression: Annotated[CompressionCodec, Profile.DEV] = Field(
        default="zstd",
        description=(
            "Codec DECLARED for Zarr field arrays and Parquet tables. The writers "
            "carry their own codec (zstd) and do not read this field, so changing "
            "it changes nothing today; it records the intent and is the field a "
            "writer would read once the choice is threaded through."
        ),
    )
    compression_level: Annotated[int, Profile.DEV] = Field(
        default=5,
        ge=0,
        le=22,
        description=(
            "Compression level DECLARED for those writers. Same as the codec: "
            "core/io/parquet.py and core/io/geoparquet.py hold level 5 and do not "
            "read this field. The default says 5 rather than 3 so the declaration "
            "at least matches the bytes actually written."
        ),
    )


__all__ = ["PersistenceConfig", "CompressionCodec"]
