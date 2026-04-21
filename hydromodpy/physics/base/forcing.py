"""Canonical forcing payload for flow boundaries and sinks/sources.

Historically HydroModPy carried near-duplicate config classes for each
forcing consumer (``FlowBoundaryForcingConstantConfig``,
``FlowBoundaryForcingCsvConfig``, ``FlowWellForcingConstantConfig``,
``FlowWellForcingCsvConfig``, etc.). The architecture spec
(``architecture_cible/02_config_pydantic.md`` §1.2) factorises these into a
single discriminated union keyed on ``kind``:

* ``ConstantForcing`` — one scalar value held over the whole simulation;
* ``CsvForcing``      — a time series loaded from a CSV file;
* ``SyntheticForcing``— an amplitude/period synthetic signal.

Consumers can accept the union directly (via the :data:`Forcing` alias) and
branch on ``kind`` for dispatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import Field

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units import FlowRate, Time


class ConstantForcing(HydroModelBase):
    """One scalar value held constant over the whole simulation."""

    kind: Literal["constant"] = Field(
        default="constant", description="Discriminator value."
    )
    value: Annotated[FlowRate, Profile.USER] = Field(
        description="Constant flow-rate value (accepts e.g. ``\"1e-3 m**3/s\"``).",
    )
    description: Annotated[str | None, Profile.DEV] = Field(
        default=None, description="Optional human-readable label."
    )


class CsvForcing(HydroModelBase):
    """Time-varying forcing backed by a CSV file on disk."""

    kind: Literal["csv"] = Field(
        default="csv", description="Discriminator value."
    )
    path: Annotated[Path, Profile.USER] = Field(
        description="Path to the CSV file. Relative paths resolve against the TOML.",
    )
    column: Annotated[str, Profile.USER] = Field(
        default="value",
        description="Name of the column holding numeric forcing values.",
    )
    datetime_column: Annotated[str, Profile.DEV] = Field(
        default="datetime",
        description="Name of the datetime column used to index the series.",
    )
    unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional source unit; if omitted the canonical unit is assumed.",
    )
    fill_method: Annotated[
        Literal["ffill", "bfill", "nearest", "none"], Profile.DEV,
    ] = Field(
        default="none",
        description="Strategy used when the series has gaps at query time.",
    )


class SyntheticForcing(HydroModelBase):
    """Synthetic amplitude/period forcing (sine-like profile)."""

    kind: Literal["synthetic"] = Field(
        default="synthetic", description="Discriminator value."
    )
    pattern: Annotated[Literal["sine", "square", "triangle"], Profile.USER] = Field(
        default="sine",
        description="Shape of the synthetic signal.",
    )
    amplitude: Annotated[FlowRate, Profile.USER] = Field(
        description="Amplitude (peak value) of the synthetic forcing.",
    )
    period: Annotated[Time, Profile.USER] = Field(
        description="Period of the synthetic signal (accepts e.g. ``\"1 day\"``).",
    )
    offset: Annotated[FlowRate | None, Profile.DEV] = Field(
        default=None, description="Optional constant offset added to the signal.",
    )


Forcing = Annotated[
    Union[ConstantForcing, CsvForcing, SyntheticForcing],
    Field(discriminator="kind"),
]
"""Discriminated union of flow-forcing payloads."""


__all__ = [
    "ConstantForcing",
    "CsvForcing",
    "Forcing",
    "SyntheticForcing",
]
