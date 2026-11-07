"""Pydantic configuration of ``[domain.layers]``, the vertical layering of the aquifer.

One table that every solver reads. It splits the column into shares (``constant``,
``decay``, ``list``) or gives each layer its own base (``surfaces``). The planar
grid is the mesh of ``[mesh]``.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from math import isclose
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.fields.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
)
from hydromodpy.core.units import LengthMeters


def _require_positive_int(value, *, name: str) -> int:
    """
    Validate and return one strictly positive integer.

    Floats representing exact integers (for example 5.0) are accepted.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= 1, got bool.")
    if isinstance(value, int):
        out = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            raise ValueError(f"{name} must be an integer value, got {value!r}.")
        out = int(value)
    else:
        raise ValueError(f"{name} must be an integer value, got {type(value)!r}.")
    if out < 1:
        raise ValueError(f"{name} must be >= 1.")
    return out


_BASE_KEYS = ("thickness", "depth", "elevation", "surface")
"""The keys that place the base of a layer, one per layer."""


class SurfaceLayerConfig(HydroModelBase):
    """One layer of a layering by surfaces: its name, its base and its minimum thickness.

    Every layer but the last gives its base with one key. The last layer ends on the
    base of the aquifer that ``[domain.depth_model]`` sets, so it gives none.
    """

    name: Annotated[IdentifierStr, Profile.USER] = Field(
        ...,
        description="Name of the layer, for example 'weathered' or 'fissured'.",
    )
    thickness: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Base this far below the base of the layer above, or below the terrain for "
            "the first layer (canonical metres)."
        ),
        examples=[30.0],
    )
    depth: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description="Base this far below the terrain (canonical meters).",
        examples=[15.0],
    )
    elevation: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        description="Base at this elevation, in the datum of the DEM (canonical meters).",
        examples=[50.0],
    )
    surface: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description=(
            "Base read from the raster of this name under [[data.layer_base.sources]], "
            "whose values are the elevation of the base."
        ),
        examples=["weathered_base"],
    )
    min_thickness: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.1,
        gt=0.0,
        description=(
            "Thinnest the layer may be (canonical metres). Where it is thinner, "
            "[domain.layers] pinch_out says what happens."
        ),
    )

    def _given_base_keys(self) -> list[str]:
        return [key for key in _BASE_KEYS if getattr(self, key) is not None]

    @property
    def base_key(self) -> str | None:
        """The key that places the base, None for a layer that gives none."""
        given = self._given_base_keys()
        return given[0] if given else None

    @model_validator(mode="after")
    def _one_base_at_most(self):
        given = self._given_base_keys()
        if len(given) > 1:
            raise ValueError(
                f"layer {self.name!r} gives its base with {' and '.join(given)}; "
                "give it with one key only."
            )
        return self


class VerticalGridConfig(HydroModelBase):
    """How the aquifer between the top and the base of ``[domain.depth_model]`` is split into layers.

    It is the ``[domain.layers]`` table, read by every solver, so a project has one
    layering whatever solver runs it. It holds the layering strategy
    (``genmtd_lay``), the layer count, proportions or layer tables, the pinch-out
    rule and the nodata sentinel.

    All geometric quantities are interpreted in SI meters.
    """

    genmtd_lay: Annotated[Literal["constant", "decay", "list", "surfaces"], Profile.USER] = Field(
        default="constant",
        description=(
            "How the aquifer thickness is split into layers: equal layers, layers that "
            "thicken with depth, the fractions you list, or one base per layer."
        ),
        json_schema_extra={
            "value_docs": {
                "constant": (
                    "Splits local thickness into nlay equal-fraction layers at every cell."
                ),
                "decay": (
                    "Grows layer thickness geometrically with depth when lay_decay is above one."
                ),
                "list": (
                    "Uses the explicit per-layer thickness fractions given in lay_proportions."
                ),
                "surfaces": (
                    "Gives each layer its own base in the [[domain.layers.layer]] tables."
                ),
            }
        },
    )
    nlay: Annotated[int | None, Profile.USER] = Field(
        default=1,
        description=(
            "Number of layers for 'constant' and 'decay'. With 'list', the number of "
            "fractions sets it, with 'surfaces' the number of layer tables."
        ),
        json_schema_extra={"unit": "-"},
    )
    lay_decay: Annotated[float | None, Profile.USER, VisibleWhen("genmtd_lay", "decay")] = Field(
        default=None,
        description=(
            "Ratio of each layer's thickness to the thickness of the layer above it, "
            "above 1. With 2, each layer is twice as thick as the one above."
        ),
        examples=[2.0],
        json_schema_extra={"unit": "-"},
    )
    lay_proportions: Annotated[
        list[float] | None, Profile.USER, VisibleWhen("genmtd_lay", "list")
    ] = Field(
        default=None,
        description=(
            "Share of the thickness each layer takes, from the top. The shares must sum to 1."
        ),
        examples=[[0.2, 0.3, 0.5]],
        json_schema_extra={"unit": "-"},
    )
    layer: Annotated[
        list[SurfaceLayerConfig] | None, Profile.USER, VisibleWhen("genmtd_lay", "surfaces")
    ] = Field(
        default=None,
        description=(
            "The layers from the top, each with its base, for 'surfaces'. The last layer "
            "ends on the base of [domain.depth_model] and gives no base."
        ),
    )
    pinch_out: Annotated[
        Literal["pass_through", "keep_min_thickness"],
        Profile.USER,
        VisibleWhen("genmtd_lay", "surfaces"),
    ] = Field(
        default="pass_through",
        description=(
            "What a layer thinner than its min_thickness becomes, for 'surfaces'. Read "
            "only with that value of genmtd_lay."
        ),
        json_schema_extra={
            "value_docs": {
                "pass_through": (
                    "The cell becomes a vertical pass-through (idomain -1, MODFLOW 6 only) "
                    "and the active cell below it, or above it at the base, takes its "
                    "thickness."
                ),
                "keep_min_thickness": (
                    "The base of the layer moves down to keep min_thickness, and the "
                    "layers below and the base of the aquifer with it. MODFLOW-NWT reads "
                    "only this value."
                ),
            }
        },
    )
    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="No-data sentinel value.",
    )

    @property
    def layer_count(self) -> int:
        """Number of layers this table builds."""
        if self.genmtd_lay == "list":
            return len(self.lay_proportions or ())
        if self.genmtd_lay == "surfaces":
            return len(self.layer or ())
        return int(self.nlay or 0)

    @property
    def vertical_layout(self) -> str:
        """How the layers are built, as a run stores it on its ``mesh/`` group."""
        if self.genmtd_lay == "surfaces":
            return VERTICAL_LAYOUT_SURFACES
        return VERTICAL_LAYOUT_COLUMN_FRACTIONS

    @property
    def has_pass_through_cells(self) -> bool:
        """True when a thin layer may become a vertical pass-through cell."""
        return self.genmtd_lay == "surfaces" and self.pinch_out == "pass_through"

    @field_validator("lay_proportions")
    @classmethod
    def _validate_lay_proportions(cls, value):
        if value is None:
            return None
        arr = [float(v) for v in list(value)]
        if len(arr) == 0:
            raise ValueError("lay_proportions cannot be empty")
        if any(v <= 0 for v in arr):
            raise ValueError("lay_proportions values must be strictly positive")
        if not isclose(sum(arr), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("lay_proportions must sum to 1.0")
        return arr

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value):
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        genmtd_lay = str(payload.get("genmtd_lay", "constant")).strip().lower()
        if genmtd_lay in {"constant", "decay"} and payload.get("nlay") is not None:
            payload["nlay"] = _require_positive_int(payload.get("nlay"), name="nlay")
        if genmtd_lay == "decay" and payload.get("lay_decay") is not None:
            payload["lay_decay"] = float(payload["lay_decay"])
        if genmtd_lay in {"list", "surfaces"}:
            if "nlay" in payload and payload.get("nlay") is not None:
                source = "lay_proportions" if genmtd_lay == "list" else "the layer tables"
                warnings.warn(
                    f"nlay must not be provided when genmtd_lay={genmtd_lay!r} "
                    f"(it is derived from {source}). "
                    "Provided nlay will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )
            payload["nlay"] = None
        return payload

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.genmtd_lay in ("constant", "decay") and self.nlay is None:
            raise ValueError("nlay is required.")
        if self.genmtd_lay == "decay":
            if self.lay_decay is None:
                raise ValueError("lay_decay is required when genmtd_lay='decay'")
            if self.lay_decay <= 1.0:
                raise ValueError("lay_decay must be > 1.0 when genmtd_lay='decay'")

        if self.genmtd_lay == "list":
            if self.lay_proportions is None:
                raise ValueError("lay_proportions is required when genmtd_lay='list'")
        if self.genmtd_lay == "surfaces":
            self._check_the_layer_tables()
        elif self.layer is not None:
            raise ValueError(
                f"[[domain.layers.layer]] is read only with genmtd_lay = 'surfaces', and "
                f"genmtd_lay is {self.genmtd_lay!r}. Write genmtd_lay = 'surfaces', or "
                "remove the layer tables."
            )
        return self

    def _check_the_layer_tables(self) -> None:
        """Refuse layer tables that do not stack: missing, unnamed twice, or a base missing."""
        layers = self.layer or []
        if not layers:
            raise ValueError(
                "genmtd_lay = 'surfaces' needs at least one [[domain.layers.layer]] table."
            )
        names = [layer.name for layer in layers]
        doubles = sorted({name for name in names if names.count(name) > 1})
        if doubles:
            raise ValueError(f"[[domain.layers.layer]] names a layer twice: {doubles}.")
        for layer in layers[:-1]:
            if layer.base_key is None:
                raise ValueError(
                    f"layer {layer.name!r} gives no base. Every layer but the last gives "
                    "its base with thickness, depth, elevation or surface."
                )
        last = layers[-1]
        if last.base_key is not None:
            raise ValueError(
                f"the last layer {last.name!r} gives its base with {last.base_key}, and it "
                "ends on the base of the aquifer [domain.depth_model] sets. Remove the "
                "key, or add a layer below it."
            )

    @property
    def base_surface_names(self) -> tuple[str, ...]:
        """Names of the ``[[data.layer_base.sources]]`` rasters the layers read."""
        if self.genmtd_lay != "surfaces":
            return ()
        return tuple(layer.surface for layer in self.layer or () if layer.surface is not None)

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        return cls.model_validate(dict(config_data))
