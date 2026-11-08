"""
Domain assembly logic built on top of `Surface` and `DomainConfig`.

This module keeps the high-level orchestration of the model domain:
- accept one already-prepared topographic surface,
- derive the vertical lower surface from the configured depth model,
- place the layer bases a layering by surfaces reads,
- expose a compact georeferencing view,
- build thematic zones (currently geology) from explicit external artifacts.

Low-level array manipulations intentionally remain delegated to `Surface`.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.core.fields.nodata import valid_cells
from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
    RasterDepthModel,
    RasterThicknessDepthModel,
)
from hydromodpy.model.domain.domain_config import DomainConfig

logger = get_logger(__name__)


def _covering_values(
    source: Surface,
    support: RasterSupport,
    cells: np.ndarray,
    *,
    name: str,
    label: str,
    hint: str = ".",
) -> np.ndarray:
    """Return *source* on the grid of *support*, refused when a cell of the domain has no value."""
    values = source.reprojected_onto(support, name=name).as_array()
    n_uncovered = int(np.count_nonzero(cells & ~np.isfinite(values)))
    if n_uncovered:
        raise DataContractViolation(
            f"The {label} leaves {n_uncovered} of the {int(np.count_nonzero(cells))} cells of "
            f"the domain without a value. It must cover the whole extent the domain is built on{hint}"
        )
    return values


class Domain:
    """
    Domain object holding geometry and thematic zones.

    Responsibilities
    ----------------
    - store the topographic surface support of the domain,
    - build the lower surface (`substratum`) from `depth_model`,
    - place the layer bases (`layer_bases`) a layering by surfaces reads,
    - keep a lightweight georeferencing mapping for legacy consumers,
    - store declared thematic zones (such as geology) once they are built outside.

    Main public attributes
    ----------------------
    - `surface_topo`
    - `substratum`
    - `layer_bases`
    - `zones`
    - `georeferencing`
    """

    def __init__(
        self,
        config: DomainConfig | Mapping[str, object] | None = None,
        *,
        surface_topo: Surface,
        substratum_source: Surface | None = None,
        layer_base_sources: Mapping[str, Surface] | None = None,
        active_cells: np.ndarray | None = None,
    ):
        self.config = self._coerce_config(config)
        self.surface_topo: Surface = surface_topo
        self.substratum: Surface | None = None
        self.layer_bases: dict[str, Surface] = {}
        self._substratum_source = substratum_source
        self._layer_base_sources = dict(layer_base_sources or {})
        self._active_cells = active_cells
        self.zones: dict[str, object] = {}
        if self.surface_topo.support is not None:
            self.georeferencing = self.surface_topo.support.as_georeferencing_dict()
        else:
            self.georeferencing = {}
        self._build_surfaces()

    @staticmethod
    def _coerce_config(
        config: DomainConfig | Mapping[str, object] | None,
    ) -> DomainConfig:
        """
        Normalize the user-provided config input into one validated `DomainConfig`.

        Accepted inputs are:
        - `None`               -> default `DomainConfig()`
        - `DomainConfig`       -> reused as-is
        - `Mapping[str, obj]`  -> validated through Pydantic
        """
        if config is None:
            return DomainConfig()
        if isinstance(config, DomainConfig):
            return config
        if not isinstance(config, Mapping):
            raise TypeError("Domain config must be a DomainConfig instance or a mapping")
        return DomainConfig.model_validate(dict(config))

    def _build_surfaces(self) -> None:
        """
        Build the lower domain surface from the configured depth model.

        Four modes are supported:
        - `ConstantThicknessDepthModel`:
          shift the topography downward by a constant offset,
        - `FlatSubstratumDepthModel`:
          create one flat surface at a constant elevation below the topography,
        - `RasterSubstratumDepthModel` and `RasterThicknessDepthModel`:
          read the substratum elevation, or the aquifer thickness, from the
          raster handed over as `substratum_source`.
        """
        depth_model = self.config.depth_model
        if self._substratum_source is not None and not isinstance(depth_model, RasterDepthModel):
            raise ValueError(
                f"A substratum raster was given, and depth_model kind "
                f"{depth_model.kind!r} does not read one."
            )
        if isinstance(depth_model, ConstantThicknessDepthModel):
            self.substratum = self.surface_topo.shifted_down_by(float(depth_model.thickness))
        elif isinstance(depth_model, FlatSubstratumDepthModel):
            self.substratum = self.surface_topo.flat_like(float(depth_model.substratum_elevation))
        else:
            self.substratum = self._substratum_from_raster(depth_model)
        self.layer_bases = self._layer_bases_from_rasters()

    def _domain_cells(self) -> tuple[np.ndarray, np.ndarray]:
        """Return the cells where the top carries data, and those narrowed to ``active_cells``."""
        support = self.surface_topo.support
        has_top = valid_cells(
            self.surface_topo.as_array(), None if support is None else support.nodata
        )
        cells = has_top if self._active_cells is None else has_top & self._active_cells
        return has_top, cells

    def _layer_bases_from_rasters(self) -> dict[str, Surface]:
        """Place every layer base ``[domain.layers]`` reads, on the grid of the top surface.

        A base is an elevation raster of ``[[data.layer_base.sources]]``. It must
        carry a value on every cell of the domain, like a substratum raster.
        """
        names = self.config.layers.base_surface_names
        extra = sorted(set(self._layer_base_sources) - set(names))
        if extra:
            raise ValueError(
                f"Layer base rasters {extra} were given, and [domain.layers] reads "
                f"{sorted(names) or 'none'}."
            )
        missing = sorted(set(names) - set(self._layer_base_sources))
        if missing:
            raise ConfigError(
                f"[domain.layers] reads the base surfaces {missing}, and none was given to "
                "the domain. Declare them under [[data.layer_base.sources]]."
            )
        if not names:
            return {}
        support = self.surface_topo.support
        if support is None:
            raise ValueError("The top surface has no RasterSupport to place a layer base on.")
        has_top, cells = self._domain_cells()
        bases: dict[str, Surface] = {}
        for name in names:
            values = _covering_values(
                self._layer_base_sources[name],
                support,
                cells,
                name=name,
                label=f"layer base raster {name!r}",
            )
            if support.nodata is not None:
                values = np.where(has_top, values, float(support.nodata))
            bases[name] = Surface(name=name, values=values, support=support)
        return bases

    def _substratum_from_raster(self, depth_model: RasterDepthModel) -> Surface:
        """Place the substratum from a raster, on the grid of the top surface.

        The raster must carry a value on every cell of the domain. Those cells
        are the ones where the top carries data, which follows
        ``geographic.domain_extent``, narrowed to ``active_cells`` when given.
        A cell outside the domain keeps the nodata sentinel of the top.
        """
        source = self._substratum_source
        if source is None:
            raise ConfigError(
                f"domain.depth_model kind {depth_model.kind!r} reads the raster declared "
                "under [data.substratum], and none was given to the domain."
            )
        support = self.surface_topo.support
        if support is None:
            raise ValueError(
                "The top surface has no RasterSupport to place a raster substratum on."
            )

        top = self.surface_topo.as_array()
        has_top, cells = self._domain_cells()
        n_cells = int(np.count_nonzero(cells))
        if n_cells == 0:
            raise ValueError("The domain holds no cell with a top elevation.")

        values = _covering_values(
            source,
            support,
            cells,
            name="substratum",
            label="substratum raster",
            hint=(
                ": the catchment for geographic.domain_extent = 'watershed', the buffered "
                "box for 'box'. Extend the raster, or choose a smaller extent."
            ),
        )

        offset = float(depth_model.offset)
        if isinstance(depth_model, RasterThicknessDepthModel):
            bottom = top - float(depth_model.scale) * values + offset
        else:
            bottom = values + offset
        ceiling = top - float(depth_model.min_thickness)
        capped = cells & (bottom > ceiling)
        n_capped = int(np.count_nonzero(capped))
        if n_capped == n_cells:
            raise ValueError(
                "The substratum raster sits within min_thickness of the top on every "
                "cell of the domain; no aquifer would remain."
            )
        if n_capped:
            logger.warning(
                "The substratum raster sits within min_thickness=%g m of the top on %d of "
                "the %d cells of the domain, up to %.3g m above top - min_thickness; "
                "those cells are lowered to top - min_thickness.",
                float(depth_model.min_thickness),
                n_capped,
                n_cells,
                float(np.max((bottom - ceiling)[capped])),
            )

        bottom = np.where(np.isfinite(bottom), np.minimum(bottom, ceiling), ceiling)
        if support.nodata is not None:
            bottom = np.where(has_top, bottom, float(support.nodata))
        return Surface(name="substratum", values=bottom, support=support)

    @property
    def z_interfaces(self) -> np.ndarray:
        """Scalar layer interfaces derived from topography and depth model.

        For a single-layer aquifer the returned array is ``[top, bottom]``
        where both values are the mean elevation of the corresponding
        surface. Raises if substratum has not been built or carries NaN
        everywhere.
        """
        import numpy as np

        if self.substratum is None:
            raise ValueError(
                "Domain.z_interfaces requires a substratum. "
                "Build the Domain via its depth_model before reading this property."
            )
        top = float(np.nanmean(self.surface_topo.as_array()))
        bottom = float(np.nanmean(self.substratum.as_array()))
        if not np.isfinite(top) or not np.isfinite(bottom):
            raise ValueError(
                "Domain.z_interfaces cannot be computed: surface_topo or substratum "
                "has no finite values."
            )
        return np.array([top, bottom], dtype=float)

    def set_zone(
        self,
        zone_id: str,
        zone_obj: object,
    ) -> None:
        """
        Register one externally-built zone object inside the domain.

        `Domain` no longer constructs thematic zones itself. The caller builds
        them explicitly (for example a `GeologyField`) and stores them here
        under one declared `zone_id`.
        """
        normalized = str(zone_id).strip().lower()
        if normalized == "":
            raise ValueError("zone_id cannot be empty")
        if self.config.zone_ids and normalized not in self.config.zone_ids:
            raise ValueError(
                f"Zone '{normalized}' is not declared in domain.zone_ids: {self.config.zone_ids}"
            )
        self.zones[normalized] = zone_obj

    def get_zone(self, zone_id: str) -> object | None:
        """Return one registered zone by canonical zone id."""
        normalized = str(zone_id).strip().lower()
        if normalized == "":
            raise ValueError("zone_id cannot be empty")
        return self.zones.get(normalized)

    def resolve_spatial_support(self, support_id: str) -> object | None:
        """Resolve one spatial support from zone id or field identifier.

        The launcher stores heterogeneous supports in ``Domain.zones`` under a
        semantic zone key (for example ``"geology"``), while field parameters
        reference the support through ``field_spatial_id`` (for example
        ``"field_geology"``). This method bridges both naming schemes.
        """
        normalized = str(support_id).strip()
        if normalized == "":
            raise ValueError("support_id cannot be empty")

        zone_match = self.zones.get(normalized.lower())
        if zone_match is not None:
            return zone_match

        matches = [
            zone_obj
            for zone_obj in self.zones.values()
            if str(getattr(zone_obj, "identifier", "")).strip() == normalized
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple domain zones match spatial support '{normalized}'.")
        return matches[0] if matches else None
