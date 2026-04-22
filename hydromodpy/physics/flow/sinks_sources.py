"""
Flow Sink/Source Models
=======================

Typed Pydantic schemas for the ``[flow.sinks_sources]`` section of HydroModPy
configuration files.

Role in the data path
---------------------
These schemas sit between user-supplied TOML/dict payloads and the solver
adapter layer.  They are **process-level** objects: they carry physical intent
(well pumping rate, recharge depth, …) without any MODFLOW-specific convention.
Conversion to solver packages (WEL, RCH, EVT stress-period dictionaries) is
done downstream in ``FlowToModflowAdapter``.

Defined models
--------------
``FlowWellConfig``
    One pumping or injection well: grid cell + flux schedule.
``FlowRechargeConfig``
    Diffuse recharge over the whole model domain, with optional negative-value
    routing to the MODFLOW EVT package.
``FlowSinksSourcesConfig``
    Top-level container that groups ``wells`` and ``recharge`` under a single
    validated namespace, mirroring the ``[flow.sinks_sources]`` TOML section.

Typical TOML usage
------------------
.. code-block:: toml

    [flow.sinks_sources.recharge]
    values      = [0.001, 0.0008, -0.0002]   # one value per stress period [m/s]
    first_clim  = "mean"                      # period-0 policy: mean of series
    negative_to_evt = true                    # negative → EVT, clip RCH to 0

    [flow.sinks_sources.wells.W1]
    cell  = [0, 10, 20]    # [lay, row, col], 0-based
    flux  = -1e-4           # m³/s, negative = pumping
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units.volumetric_flow import normalize_m3_per_s_unit

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_common.grid_context import GridReference


class FlowWellConfig(HydroModelBase):
    """
    Typed payload for one pumping or injection well.

    A well is defined by:
    - its **location** in the MODFLOW grid (``cell``),
    - its **flux schedule** over time (``flux``).

    Conventions
    -----------
    - ``cell`` uses **0-based** ``(lay, row, col)`` indexing, consistent with
      FLOPY and the rest of HydroModPy.
    - ``flux`` follows the MODFLOW sign convention: **negative = pumping**
      (extraction), positive = injection.
    - ``flux`` may be a **scalar** (same rate for every stress period) or a
      **list** with one value per stress period.
    """

    model_config = ConfigDict(extra="forbid")

    cell: Annotated[tuple[int, int, int] | None, Profile.USER] = Field(
        default=None,
        description="Legacy cell indices as [lay, row, col] (0-based).",
    )
    location_mode: Annotated[Literal["cell", "absolute_xy", "relative_xy"] | None, Profile.USER] = (
        Field(
            default=None,
            description=(
                "Well location mode. Use 'cell' for legacy [lay,row,col], "
                "'absolute_xy' for projected coordinates, or 'relative_xy' for "
                "normalized horizontal coordinates in the domain extent."
            ),
        )
    )
    layer: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Layer index (0-based) used with absolute_xy or relative_xy modes.",
    )
    x: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Projected X coordinate used when location_mode='absolute_xy'.",
    )
    y: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Projected Y coordinate used when location_mode='absolute_xy'.",
    )
    x_rel: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Relative X position in [0,1] from west to east when location_mode='relative_xy'.",
    )
    y_rel: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Relative Y position in [0,1] from south to north when location_mode='relative_xy'.",
    )
    flux: Annotated[float | list[float] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Well rate [L³/T]. Scalar for constant rate, or one value per stress period. "
            "Negative = pumping, positive = injection."
        ),
    )
    forcing: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional runtime forcing declaration. Supported modes: "
            "'constant' and 'csv'. The launcher resolves this payload to "
            "well.flux using [simulation.time]."
        ),
    )
    units: Annotated[str, Profile.DEV] = Field(default="m3/s", description="Units of flux values.")
    description: Annotated[str, Profile.USER] = Field(
        default="", description="Optional well description."
    )

    @field_validator("cell", mode="before")
    @classmethod
    def _validate_cell(cls, value):
        """
        Normalize cell addressing into a strict ``(lay, row, col)`` integer tuple.

        Accepted input forms:
        - mapping  : ``{"lay": 0, "row": 5, "col": 10}``
        - sequence : ``[0, 5, 10]`` or ``(0, 5, 10)``

        All three axis values must be non-negative integers (floats that are
        whole numbers are accepted and silently cast to int).
        """
        if value is None:
            return None
        if isinstance(value, Mapping):
            # Extract from dict-like payload; raise early if a key is missing.
            try:
                raw_seq = [value["lay"], value["row"], value["col"]]
            except KeyError as exc:
                raise ValueError("well.cell mapping must define lay, row, and col") from exc
        elif isinstance(value, (list, tuple)):
            raw_seq = list(value)
        else:
            raise TypeError("well.cell must be a mapping or a 3-item list [lay, row, col]")

        if len(raw_seq) != 3:
            raise ValueError("well.cell must contain exactly 3 values: [lay, row, col]")

        # Parse each axis independently so validation errors name the offending axis.
        parsed: list[int] = []
        for axis, raw_item in zip(("lay", "row", "col"), raw_seq, strict=False):
            # Booleans are a subclass of int in Python; reject them explicitly.
            if isinstance(raw_item, bool):
                raise TypeError(f"well.cell.{axis} must be an integer")
            if isinstance(raw_item, Real):
                numeric = float(raw_item)
                # Accept only whole-number floats (e.g. 2.0 → 2).
                if not numeric.is_integer():
                    raise TypeError(f"well.cell.{axis} must be an integer")
                index_value = int(numeric)
            else:
                raise TypeError(f"well.cell.{axis} must be an integer")
            # Grid indices cannot be negative.
            if index_value < 0:
                raise ValueError(f"well.cell.{axis} must be >= 0")
            parsed.append(index_value)
        return tuple(parsed)

    @field_validator("location_mode", mode="before")
    @classmethod
    def _validate_location_mode(cls, value):
        """Normalize well location mode strings."""
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized == "":
            return None
        if normalized not in {"cell", "absolute_xy", "relative_xy"}:
            raise ValueError("well.location_mode must be one of: cell, absolute_xy, relative_xy")
        return normalized

    @field_validator("layer", mode="before")
    @classmethod
    def _validate_layer(cls, value):
        """Validate one layer index used by coordinate-based well addressing."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("well.layer must be an integer")
        numeric = float(value)
        if not numeric.is_integer():
            raise TypeError("well.layer must be an integer")
        layer = int(numeric)
        if layer < 0:
            raise ValueError("well.layer must be >= 0")
        return layer

    @field_validator("x", "y", mode="before")
    @classmethod
    def _validate_absolute_coordinate(cls, value):
        """Validate one projected coordinate component."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("well absolute coordinates must be numeric")
        return float(value)

    @field_validator("x_rel", "y_rel", mode="before")
    @classmethod
    def _validate_relative_coordinate(cls, value):
        """Validate one relative coordinate component."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("well relative coordinates must be numeric")
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("well relative coordinates must be within [0, 1]")
        return numeric

    @field_validator("flux", mode="before")
    @classmethod
    def _validate_flux(cls, value):
        """
        Validate and normalize the flux schedule.

        - A single numeric value is kept as ``float``.
        - A list/tuple is converted to ``list[float]``.
        - Empty lists and non-numeric items are rejected.
        """
        if value is None:
            return None
        # Booleans would pass `isinstance(value, Real)`; block them first.
        if isinstance(value, bool):
            raise TypeError("well.flux must be numeric or a list of numeric values")
        if isinstance(value, Real):
            # Constant flux across all stress periods.
            return float(value)
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError("well.flux list cannot be empty")
            parsed: list[float] = []
            for idx, raw_item in enumerate(value):
                if isinstance(raw_item, bool) or not isinstance(raw_item, Real):
                    raise TypeError(f"well.flux[{idx}] must be numeric")
                parsed.append(float(raw_item))
            return parsed
        raise TypeError("well.flux must be numeric or a list of numeric values")

    @model_validator(mode="after")
    def _validate_location_payload(self):
        """Enforce one unambiguous location grammar for each well."""
        if self.cell is not None:
            if self.location_mode is None:
                object.__setattr__(self, "location_mode", "cell")
            if self.location_mode != "cell":
                raise ValueError("well.cell cannot be combined with a non-'cell' location_mode")
            if any(
                value is not None for value in (self.layer, self.x, self.y, self.x_rel, self.y_rel)
            ):
                raise ValueError(
                    "well.cell cannot be combined with layer/x/y/x_rel/y_rel; "
                    "use either cell or coordinate-based location fields"
                )
        else:
            if self.location_mode is None:
                raise ValueError(
                    "well location requires either cell=[lay,row,col] or "
                    "location_mode with coordinate fields"
                )

            if self.location_mode == "cell":
                raise ValueError("well.location_mode='cell' requires cell=[lay,row,col]")

            if self.layer is None:
                object.__setattr__(self, "layer", 0)

            if self.location_mode == "absolute_xy":
                if self.x is None or self.y is None:
                    raise ValueError("well.location_mode='absolute_xy' requires x and y")
                if self.x_rel is not None or self.y_rel is not None:
                    raise ValueError(
                        "well.location_mode='absolute_xy' cannot be combined with x_rel/y_rel"
                    )
            elif self.location_mode == "relative_xy":
                if self.x_rel is None or self.y_rel is None:
                    raise ValueError("well.location_mode='relative_xy' requires x_rel and y_rel")
                if self.x is not None or self.y is not None:
                    raise ValueError("well.location_mode='relative_xy' cannot be combined with x/y")

        if self.flux is None and self.forcing is None:
            raise ValueError("well requires either flux or forcing")
        if self.flux is not None and self.forcing is not None:
            raise ValueError("well.flux and well.forcing are mutually exclusive")
        if self.forcing is not None:
            parent_units = str(self.units).strip() or "m3/s"
            forcing_units = getattr(self.forcing, "units", None)
            parent_units_explicit = "units" in self.model_fields_set
            forcing_units_explicit = "units" in self.forcing.model_fields_set
            if forcing_units_explicit:
                normalized_forcing_units = normalize_m3_per_s_unit(
                    str(forcing_units).strip() or "m3/s"
                )
                if parent_units_explicit:
                    normalized_parent_units = normalize_m3_per_s_unit(parent_units)
                    if (
                        normalized_parent_units != "m3/s"
                        and normalized_parent_units != normalized_forcing_units
                    ):
                        raise ValueError("well.units conflicts with well.forcing.units")
            else:
                normalized_forcing_units = normalize_m3_per_s_unit(parent_units)
            object.__setattr__(
                self,
                "forcing",
                self.forcing.model_copy(update={"units": normalized_forcing_units}),
            )
            object.__setattr__(self, "units", "m3/s")

        return self

    def resolve_cell(self, grid: GridReference) -> tuple[int, int, int]:
        """Resolve this well location against one solver grid."""
        if self.cell is not None:
            return self.cell

        if self.location_mode == "absolute_xy":
            x = float(self.x)
            y = float(self.y)
        elif self.location_mode == "relative_xy":
            x = float(grid.xmin) + float(self.x_rel) * (float(grid.xmax) - float(grid.xmin))
            y = float(grid.ymin) + float(self.y_rel) * (float(grid.ymax) - float(grid.ymin))
        else:
            raise ValueError("well location cannot be resolved without cell or coordinate mode")

        col = int((x - float(grid.xmin)) / float(grid.dx))
        row = int((float(grid.ymax) - y) / float(grid.dy))
        col = min(max(col, 0), int(grid.ncol) - 1)
        row = min(max(row, 0), int(grid.nrow) - 1)
        return (int(self.layer), row, col)


class FlowWellForcingConstantConfig(HydroModelBase):
    """One constant well-rate forcing applied to every stress period."""

    model_config = ConfigDict(extra="forbid")

    value: Annotated[float, Profile.USER] = Field(
        ...,
        description="Constant well rate in the same units as the parent well.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("well.forcing.value must be numeric")
        return float(value)


class FlowWellForcingCsvConfig(HydroModelBase):
    """CSV-backed well forcing resolved at runtime against simulation.time."""

    model_config = ConfigDict(extra="forbid")

    path_file: Annotated[Path, Profile.DEV] = Field(
        ..., description="Path to the CSV chronicle file."
    )
    sep: Annotated[str, Profile.DEV] = Field(default=",", description="CSV delimiter.")
    date_column: Annotated[str, Profile.DEV] = Field(
        default="date", description="CSV column containing timestamps."
    )
    date_format: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: Annotated[str, Profile.DEV] = Field(
        default="value", description="CSV column containing well rates."
    )
    fill_method: Annotated[Literal["ffill", "bfill"], Profile.DEV] = Field(
        default="ffill",
        description="Gap-filling policy used when a stress period has no direct sample.",
    )
    aggregate: Annotated[Literal["mean", "last"], Profile.DEV] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )

    @field_validator("sep", "date_column", "value_column", mode="before")
    @classmethod
    def _validate_text_fields(cls, value, info):
        text = str(value).strip()
        if text == "":
            raise ValueError(f"well.forcing.{info.field_name} cannot be empty")
        return text


class FlowWellForcingConfig(HydroModelBase):
    """Launcher-facing well forcing declaration."""

    model_config = ConfigDict(extra="forbid")

    mode: Annotated[Literal["constant", "csv"], Profile.USER] = Field(
        ...,
        description="Well forcing mode consumed by launcher runtime.",
    )
    units: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Source units of forcing values before runtime conversion.",
    )
    value: Annotated[float | None, Profile.USER] = Field(default=None)
    path_file: Annotated[Path | None, Profile.DEV] = Field(default=None)
    sep: Annotated[str, Profile.DEV] = Field(default=",")
    date_column: Annotated[str, Profile.DEV] = Field(default="date")
    date_format: Annotated[str | None, Profile.DEV] = Field(default=None)
    value_column: Annotated[str, Profile.DEV] = Field(default="value")
    fill_method: Annotated[Literal["ffill", "bfill"], Profile.DEV] = Field(default="ffill")
    aggregate: Annotated[Literal["mean", "last"], Profile.DEV] = Field(default="mean")

    @model_validator(mode="after")
    def _validate_mode_payload(self):
        if self.mode == "constant":
            if self.value is None:
                raise ValueError("well.forcing.mode='constant' requires value")
            return self
        if self.path_file is None:
            raise ValueError("well.forcing.mode='csv' requires path_file")
        return self

    def as_constant(self) -> FlowWellForcingConstantConfig:
        if self.mode != "constant":
            raise ValueError("well forcing is not in constant mode")
        return FlowWellForcingConstantConfig(value=self.value)

    def as_csv(self) -> FlowWellForcingCsvConfig:
        if self.mode != "csv":
            raise ValueError("well forcing is not in csv mode")
        return FlowWellForcingCsvConfig(
            path_file=self.path_file,
            sep=self.sep,
            date_column=self.date_column,
            date_format=self.date_format,
            value_column=self.value_column,
            fill_method=self.fill_method,
            aggregate=self.aggregate,
        )


class FlowRechargeConfig(HydroModelBase):
    """
    Typed payload for diffuse recharge over the model domain.

    Recharge drives the MODFLOW RCH package.  When ``negative_to_evt`` is True,
    negative values are split off to activate the EVT package (actual
    evapotranspiration) and the RCH values are clipped to zero.

    This object belongs to ``flow.sinks_sources`` and is solver-agnostic: the
    actual conversion to MODFLOW stress-period dictionaries is handled by
    ``FlowToModflowAdapter._build_recharge_payload``.

    Attributes
    ----------
    values :
        Recharge payload.  Accepted forms:

        - **scalar** ``float``: uniform rate applied to every stress period,
        - **list / numpy array**: one value per stress period
          (length must match ``nper``),
        - **mapping** ``{period_index: value}``: explicit per-period assignment,
        - **runtime series** (pandas-like object with ``.iloc``): used when
          recharge is computed dynamically (e.g. from PyHELP output).

    first_clim : str | float
        Policy for stress-period 0 when ``values`` is a sequence.
        MODFLOW steady-state warm-up periods often need a representative rate
        that differs from the first raw time step.  Options:

        - ``"mean"``: arithmetic mean of the entire series (default),
        - ``"first"``: first value of the series,
        - *numeric*: explicit scalar (e.g. long-term average from literature).

    units : str
        Physical units of ``values``. The flow runtime converts the payload
        to SI ``m/s`` when the process is built.

    negative_to_evt : bool
        When ``True`` (default), negative recharge values are treated as net
        evapotranspiration:

        - the absolute value feeds the MODFLOW EVT package,
        - the RCH value for that period is clipped to 0.

        Only meaningful when ``values`` is a non-mapping sequence or scalar.
        Mapping payloads do not trigger EVT regardless of this flag (see
        ``FlowToModflowAdapter._build_recharge_payload``).
    """

    model_config = ConfigDict(extra="forbid")

    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "Recharge payload: scalar, list (one per stress period), "
            "mapping {kper: value}, or runtime series."
        ),
    )
    heterogeneous_source: Annotated[Any, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional raw data source for heterogeneous (2D per-cell) recharge. "
            "When set, the solver adapter discretizes FieldRecords onto the "
            "MODFLOW grid instead of using the scalar 'values' field. "
            "Expected: LoadResult with FieldRecords."
        ),
    )
    first_clim: Annotated[str | float, Profile.DEV] = Field(
        default="mean",
        description=(
            "Period-0 policy when values is a sequence: "
            "'mean' (series average), 'first' (first element), or a numeric scalar."
        ),
    )
    units: Annotated[str, Profile.DEV] = Field(
        default="mm/day",
        description=(
            "Units of the recharge data source. Data-manager outputs use "
            "mm/day by convention; override when providing values in another "
            "unit (e.g. 'm/day'). Converted to m/s at runtime via "
            "factor_to_m_per_s()."
        ),
    )
    negative_to_evt: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description=(
            "Route negative recharge to the EVT package and clip RCH to 0. "
            "Ignored for mapping payloads."
        ),
    )
    spatial_mode: Annotated[str, Profile.DEV] = Field(
        default="auto",
        description=(
            "How to interpret spatial data: 'auto' (points→homogeneous, "
            "fields→heterogeneous), 'homogeneous' (force spatial averaging), "
            "'heterogeneous' (force per-cell discretization, including "
            "point-to-grid interpolation when stations have coordinates)."
        ),
    )
    interpolation_method: Annotated[str, Profile.DEV] = Field(
        default="nearest",
        description=(
            "Spatial interpolation method for gridded/point data onto the "
            "MODFLOW grid. Options: 'nearest', 'linear', 'idw'."
        ),
    )

    @field_validator("spatial_mode", mode="before")
    @classmethod
    def _validate_spatial_mode(cls, value):
        v = str(value).strip().lower()
        if v not in {"auto", "homogeneous", "heterogeneous"}:
            raise ValueError("spatial_mode must be 'auto', 'homogeneous', or 'heterogeneous'.")
        return v

    @field_validator("interpolation_method", mode="before")
    @classmethod
    def _validate_interpolation_method(cls, value):
        v = str(value).strip().lower()
        if v not in {"nearest", "linear", "idw"}:
            raise ValueError("interpolation_method must be 'nearest', 'linear', or 'idw'.")
        return v

    @field_validator("first_clim", mode="before")
    @classmethod
    def _validate_first_clim(cls, value):
        """
        Normalize and validate the ``first_clim`` policy.

        Accepted values:
        - string ``"mean"`` or ``"first"`` (case-insensitive),
        - any numeric scalar (stored as ``float``).

        This normalization runs at Pydantic validation time so that downstream
        code in ``FlowToModflowAdapter`` can rely on a canonical lowercase string
        or a plain float without any further checks.
        """
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in {"mean", "first"}:
                raise ValueError("first_clim must be 'mean', 'first', or a numeric value.")
            return normalized
        # Booleans are a subclass of int/Real; reject them explicitly to avoid
        # silent conversion (True → 1.0, False → 0.0 would be misleading).
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("first_clim must be 'mean', 'first', or a numeric value.")
        return float(value)


class FlowSinksSourcesConfig(HydroModelBase):
    """
    Top-level container for all sink/source elements of the flow process.

    Maps directly to the ``[flow.sinks_sources]`` TOML section.  Both fields
    are optional so that a minimal ``FlowSinksSourcesConfig()`` (no wells, no
    recharge) is always valid and represents a passive model with zero recharge.

    Fields
    ------
    wells : dict[str, FlowWellConfig]
        Pumping/injection wells keyed by a user-defined string id.
        An empty dict means no wells are active.
    recharge : FlowRechargeConfig | None
        Diffuse recharge configuration.  ``None`` means no recharge is
        configured; the adapter will default to zero recharge for all periods.
    """

    model_config = ConfigDict(extra="forbid")

    wells: Annotated[dict[str, FlowWellConfig], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )
    recharge: Annotated[FlowRechargeConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Diffuse recharge (and optional EVT) configuration. "
            "None = zero recharge for all periods."
        ),
    )

    @field_validator("wells", mode="before")
    @classmethod
    def _validate_wells(cls, value):
        """
        Normalize and validate the wells mapping before per-item Pydantic validation.

        This pre-validation step:
        - converts ``None`` to an empty dict (no wells),
        - rejects non-mapping inputs early with a clear message,
        - strips whitespace from well ids and rejects empty-string keys.

        Per-well payload validation (cell, flux) is delegated to
        ``FlowWellConfig`` which Pydantic calls for each value in the returned
        dict.
        """
        if value is None:
            # Treat missing wells section as an empty dict, not an error.
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.wells must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            # Normalize key to a clean string; empty ids are ambiguous and rejected.
            well_id = str(raw_key).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty well ids")
            out[well_id] = raw_payload
        return out
