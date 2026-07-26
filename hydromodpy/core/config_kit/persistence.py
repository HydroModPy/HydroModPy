"""Single-switch persistence configuration (Principe 8).

``PersistenceConfig`` is the orthogonal save/no-save knob shared by every
write path: the DuckDB Catalog and the per-run Zarr and Parquet artifacts.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

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
    save_parquet: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Persist per-simulation tabular outputs (timeseries, "
        "budgets, mass_balance) as Parquet files.",
    )
    compression: Annotated[CompressionCodec, Profile.DEV] = Field(
        default="zstd",
        description="Codec used for Zarr field arrays and Parquet tables. "
        "'none' disables compression.",
    )
    compression_level: Annotated[int, Profile.DEV] = Field(
        default=3,
        ge=0,
        le=22,
        description="Compression level (codec-dependent). Ignored when compression='none'.",
    )


__all__ = ["PersistenceConfig", "CompressionCodec"]
