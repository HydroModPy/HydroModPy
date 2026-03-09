# -*- coding: utf-8 -*-
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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_common.grid_context import GridReference


class FlowWellConfig(BaseModel):
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

    cell: tuple[int, int, int] | None = Field(
        default=None,
        description="Legacy cell indices as [lay, row, col] (0-based).",
    )
    location_mode: Literal["cell", "absolute_xy", "relative_xy"] | None = Field(
        default=None,
        description=(
            "Well location mode. Use 'cell' for legacy [lay,row,col], "
            "'absolute_xy' for projected coordinates, or 'relative_xy' for "
            "normalized horizontal coordinates in the domain extent."
        ),
    )
    layer: int | None = Field(
        default=None,
        description="Layer index (0-based) used with absolute_xy or relative_xy modes.",
    )
    x: float | None = Field(
        default=None,
        description="Projected X coordinate used when location_mode='absolute_xy'.",
    )
    y: float | None = Field(
        default=None,
        description="Projected Y coordinate used when location_mode='absolute_xy'.",
    )
    x_rel: float | None = Field(
        default=None,
        description="Relative X position in [0,1] from west to east when location_mode='relative_xy'.",
    )
    y_rel: float | None = Field(
        default=None,
        description="Relative Y position in [0,1] from south to north when location_mode='relative_xy'.",
    )
    flux: float | list[float] = Field(
        ...,
        description=(
            "Well rate [L³/T]. Scalar for constant rate, or one value per stress period. "
            "Negative = pumping, positive = injection."
        ),
    )
    units: str = Field(default="m3/s", description="Units of flux values.")
    description: str = Field(default="", description="Optional well description.")

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
        for axis, raw_item in zip(("lay", "row", "col"), raw_seq):
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
            raise ValueError(
                "well.location_mode must be one of: cell, absolute_xy, relative_xy"
            )
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
                self.location_mode = "cell"
            if self.location_mode != "cell":
                raise ValueError("well.cell cannot be combined with a non-'cell' location_mode")
            if any(value is not None for value in (self.layer, self.x, self.y, self.x_rel, self.y_rel)):
                raise ValueError(
                    "well.cell cannot be combined with layer/x/y/x_rel/y_rel; "
                    "use either cell or coordinate-based location fields"
                )
            return self

        if self.location_mode is None:
            raise ValueError(
                "well location requires either cell=[lay,row,col] or "
                "location_mode with coordinate fields"
            )

        if self.location_mode == "cell":
            raise ValueError("well.location_mode='cell' requires cell=[lay,row,col]")

        if self.layer is None:
            self.layer = 0

        if self.location_mode == "absolute_xy":
            if self.x is None or self.y is None:
                raise ValueError("well.location_mode='absolute_xy' requires x and y")
            if self.x_rel is not None or self.y_rel is not None:
                raise ValueError("well.location_mode='absolute_xy' cannot be combined with x_rel/y_rel")
        elif self.location_mode == "relative_xy":
            if self.x_rel is None or self.y_rel is None:
                raise ValueError("well.location_mode='relative_xy' requires x_rel and y_rel")
            if self.x is not None or self.y is not None:
                raise ValueError("well.location_mode='relative_xy' cannot be combined with x/y")

        return self

    def resolve_cell(self, grid: "GridReference") -> tuple[int, int, int]:
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


class FlowRechargeConfig(BaseModel):
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
        Physical units of ``values``, for documentation purposes only.
        Default is ``"m/s"``; conversion is the user's responsibility.

    negative_to_evt : bool
        When ``True`` (default), negative recharge values are treated as net
        evapotranspiration:

        - the absolute value feeds the MODFLOW EVT package,
        - the RCH value for that period is clipped to 0.

        Only meaningful when ``values`` is a non-mapping sequence or scalar.
        Mapping payloads do not trigger EVT regardless of this flag (see
        ``FlowToModflowAdapter._build_recharge_payload``).
    """

    values: Any = Field(
        default=0.0,
        description=(
            "Recharge payload: scalar, list (one per stress period), "
            "mapping {kper: value}, or runtime series."
        ),
    )
    first_clim: str | float = Field(
        default="mean",
        description=(
            "Period-0 policy when values is a sequence: "
            "'mean' (series average), 'first' (first element), or a numeric scalar."
        ),
    )
    units: str = Field(
        default="m/s",
        description="Units of recharge values (informational only).",
    )
    negative_to_evt: bool = Field(
        default=True,
        description=(
            "Route negative recharge to the EVT package and clip RCH to 0. "
            "Ignored for mapping payloads."
        ),
    )

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


class FlowSinksSourcesConfig(BaseModel):
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

    wells: dict[str, FlowWellConfig] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )
    recharge: FlowRechargeConfig | None = Field(
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
