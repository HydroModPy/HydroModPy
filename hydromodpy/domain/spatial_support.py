from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    DomainSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)
from hydromodpy.field.core.field_mesh import BaseFieldMesh
from hydromodpy.field.core.field_spatial import Field
from hydromodpy.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


def _sample_points_in_cell(cell, *, n_sub_per_axis: int):
    """Generate deterministic interior sample points for one mesh cell."""
    n = max(2, int(n_sub_per_axis))
    verts = np.asarray(cell.vertices, dtype=float)

    if cell.kind == "quadrilateral":
        u = (np.arange(n, dtype=float) + 0.5) / float(n)
        v = (np.arange(n, dtype=float) + 0.5) / float(n)
        uu, vv = np.meshgrid(u, v, indexing="xy")
        w0 = (1.0 - uu) * (1.0 - vv)
        w1 = uu * (1.0 - vv)
        w2 = uu * vv
        w3 = (1.0 - uu) * vv
        x = w0 * verts[0, 0] + w1 * verts[1, 0] + w2 * verts[2, 0] + w3 * verts[3, 0]
        y = w0 * verts[0, 1] + w1 * verts[1, 1] + w2 * verts[2, 1] + w3 * verts[3, 1]
        return x.ravel(), y.ravel()

    if cell.kind == "triangle":
        u = (np.arange(n, dtype=float) + 0.5) / float(n)
        v = (np.arange(n, dtype=float) + 0.5) / float(n)
        uu, vv = np.meshgrid(u, v, indexing="xy")
        mask = (uu + vv) < 1.0
        uu = uu[mask]
        vv = vv[mask]
        p0, p1, p2 = verts[0], verts[1], verts[2]
        x = p0[0] + uu * (p1[0] - p0[0]) + vv * (p2[0] - p0[0])
        y = p0[1] + uu * (p1[1] - p0[1]) + vv * (p2[1] - p0[1])
        return x, y

    raise ValueError(f"Unsupported cell kind '{cell.kind}'")


class AliasedSpatialSupportField(Field):
    """Delegate one support field while exposing a different public identifier."""

    def __init__(self, *, identifier: str, delegate: object):
        super().__init__(identifier=identifier)
        self.delegate = delegate
        self.default_cell_samples_per_axis = int(
            getattr(delegate, "default_cell_samples_per_axis", 8)
        )

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return tuple(getattr(self.delegate, "zone_keys", ()))

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        return self.delegate.on_mesh(mesh, cell_samples_per_axis=cell_samples_per_axis)

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)


class RasterZonesSupportField(Field):
    """Generic raster-like zonation support aligned with one domain raster support."""

    def __init__(
        self,
        *,
        identifier: str,
        encoded_codes,
        encoded_to_zone: dict[int, str],
        raster_support: RasterSupport,
        nodata_code: int = 0,
        source_meta: dict[str, str] | None = None,
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        codes = np.asarray(encoded_codes, dtype=np.int32)
        if codes.ndim != 2:
            raise ValueError("encoded_codes must be a 2D integer array")
        if codes.size == 0:
            raise ValueError("encoded_codes cannot be empty")

        mapping = {int(key): str(value).strip() for key, value in dict(encoded_to_zone).items()}
        if not mapping:
            raise ValueError("encoded_to_zone cannot be empty")
        if any(code <= 0 for code in mapping):
            raise ValueError("encoded_to_zone keys must be positive integers")
        if any(label == "" for label in mapping.values()):
            raise ValueError("encoded_to_zone labels cannot be empty")

        if not isinstance(raster_support, RasterSupport):
            raise TypeError("raster_support must be a RasterSupport instance")
        raster_support.assert_complete_domain()
        if raster_support.dx is None or raster_support.dy is None:
            raise ValueError("raster_support must expose dx and dy")

        if raster_support.nrows != codes.shape[0] or raster_support.ncols != codes.shape[1]:
            raise ValueError(
                "raster_support shape mismatch with encoded_codes: "
                f"{(raster_support.nrows, raster_support.ncols)} != {codes.shape}"
            )

        allowed = set(mapping) | {int(nodata_code)}
        present = set(np.unique(codes).astype(int).tolist())
        if not present.issubset(allowed):
            unknown = sorted(present.difference(allowed))
            raise ValueError(f"encoded_codes contains unknown class codes: {unknown}")

        self.encoded_codes = codes
        self.encoded_to_zone = mapping
        self.raster_support = raster_support
        self.nodata_code = int(nodata_code)
        self.source_meta = None if source_meta is None else dict(source_meta)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return tuple(self.encoded_to_zone[key] for key in sorted(self.encoded_to_zone))

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(int(value) for value in self.encoded_codes.shape)

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x and y must have the same shape")

        support = self.raster_support
        xmin = float(support.xmin)
        xmax = float(support.xmax)
        ymin = float(support.ymin)
        ymax = float(support.ymax)
        dx = float(support.dx)
        dy = float(support.dy)
        nrows, ncols = self.shape

        cols = np.floor((x_arr.ravel() - xmin) / dx).astype(int)
        rows = np.floor((ymax - y_arr.ravel()) / dy).astype(int)

        out = np.empty(rows.shape, dtype=object)
        out[:] = ""
        valid = (
            (x_arr.ravel() >= xmin)
            & (x_arr.ravel() < xmax)
            & (y_arr.ravel() >= ymin)
            & (y_arr.ravel() < ymax)
            & (rows >= 0)
            & (rows < nrows)
            & (cols >= 0)
            & (cols < ncols)
        )
        if np.any(valid):
            valid_codes = self.encoded_codes[rows[valid], cols[valid]]
            mapped = np.empty(valid_codes.shape, dtype=object)
            mapped[:] = ""
            for encoded in np.unique(valid_codes):
                if int(encoded) <= 0 or int(encoded) == self.nodata_code:
                    continue
                zone_key = self.encoded_to_zone.get(int(encoded), "")
                if zone_key:
                    mapped[valid_codes == int(encoded)] = zone_key
            out[valid] = mapped
        return out.reshape(x_arr.shape)

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        fractions_by_zone = {
            zone_key: np.zeros(mesh.n_cells, dtype=float) for zone_key in self.zone_keys
        }
        n_sub = max(2, int(cell_samples_per_axis))

        for cell in mesh.cells:
            x_samples, y_samples = _sample_points_in_cell(cell, n_sub_per_axis=n_sub)
            zone_ids = self.zone_id(x_samples, y_samples)
            total = max(int(np.count_nonzero(zone_ids != "")), 1)
            for zone_key in self.zone_keys:
                count = int(np.count_nonzero(zone_ids == zone_key))
                fractions_by_zone[zone_key][cell.index] = float(count) / float(total)

        mesh_values = {
            zone_key: np.asarray(mesh.to_cell_values(values), dtype=float)
            for zone_key, values in fractions_by_zone.items()
        }
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=self.zone_keys,
            fractions_by_zone=mesh_values,
        )


class GeneratedBandsSupportField(Field):
    """Analytical band support split along one horizontal axis."""

    def __init__(
        self,
        *,
        identifier: str,
        axis: Literal["x", "y"],
        breaks_abs: list[float],
        labels: list[str],
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        self.axis = str(axis).strip().lower()
        self.breaks_abs = [float(value) for value in breaks_abs]
        self.labels = tuple(str(label).strip() for label in labels)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return self.labels

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        coord = x_arr if self.axis == "x" else y_arr
        bins = np.asarray(self.breaks_abs, dtype=float)
        indexes = np.searchsorted(bins, coord, side="right")
        labels = np.asarray(self.labels, dtype=object)
        return labels[indexes]

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        fractions_by_zone = {
            zone_key: np.zeros(mesh.n_cells, dtype=float) for zone_key in self.zone_keys
        }
        n_sub = max(2, int(cell_samples_per_axis))
        for cell in mesh.cells:
            x_samples, y_samples = _sample_points_in_cell(cell, n_sub_per_axis=n_sub)
            zone_ids = self.zone_id(x_samples, y_samples)
            total = max(zone_ids.size, 1)
            for zone_key in self.zone_keys:
                count = int(np.count_nonzero(zone_ids == zone_key))
                fractions_by_zone[zone_key][cell.index] = float(count) / float(total)

        mesh_values = {
            zone_key: np.asarray(mesh.to_cell_values(values), dtype=float)
            for zone_key, values in fractions_by_zone.items()
        }
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=self.zone_keys,
            fractions_by_zone=mesh_values,
        )


class GeneratedRingsSupportField(Field):
    """Analytical concentric rings centered on one cartesian point."""

    def __init__(
        self,
        *,
        identifier: str,
        center_x: float,
        center_y: float,
        radii_abs: list[float],
        labels: list[str],
        default_cell_samples_per_axis: int = 8,
    ):
        super().__init__(identifier=identifier)
        self.center_x = float(center_x)
        self.center_y = float(center_y)
        self.radii_abs = [float(value) for value in radii_abs]
        self.labels = tuple(str(label).strip() for label in labels)
        self.default_cell_samples_per_axis = max(2, int(default_cell_samples_per_axis))

        if any(value <= 0.0 for value in self.radii_abs):
            raise ValueError("radii_abs must contain only strictly positive values")
        if self.radii_abs != sorted(self.radii_abs):
            raise ValueError("radii_abs must be strictly increasing")
        if len(set(self.radii_abs)) != len(self.radii_abs):
            raise ValueError("radii_abs cannot contain duplicates")
        if len(self.labels) != len(self.radii_abs) + 1:
            raise ValueError("labels length must be len(radii_abs) + 1")
        if any(label == "" for label in self.labels):
            raise ValueError("labels cannot contain empty values")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels cannot contain duplicates")

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return self.labels

    def zone_id(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        radius = np.sqrt((x_arr - self.center_x) ** 2 + (y_arr - self.center_y) ** 2)
        labels = np.asarray(self.labels, dtype=object)
        indexes = np.searchsorted(np.asarray(self.radii_abs, dtype=float), radius, side="right")
        return labels[indexes]

    def on_mesh(self, mesh: BaseFieldMesh, *, cell_samples_per_axis: int = 10):
        fractions_by_zone = {
            zone_key: np.zeros(mesh.n_cells, dtype=float) for zone_key in self.zone_keys
        }
        n_sub = max(2, int(cell_samples_per_axis))
        for cell in mesh.cells:
            x_samples, y_samples = _sample_points_in_cell(cell, n_sub_per_axis=n_sub)
            zone_ids = self.zone_id(x_samples, y_samples)
            total = max(zone_ids.size, 1)
            for zone_key in self.zone_keys:
                count = int(np.count_nonzero(zone_ids == zone_key))
                fractions_by_zone[zone_key][cell.index] = float(count) / float(total)

        mesh_values = {
            zone_key: np.asarray(mesh.to_cell_values(values), dtype=float)
            for zone_key, values in fractions_by_zone.items()
        }
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=self.zone_keys,
            fractions_by_zone=mesh_values,
        )


@dataclass(slots=True)
class SupportBuildContext:
    """Runtime objects available when building domain spatial supports."""

    cfg: object
    raw_toml: dict[str, object]
    workspace: object | None
    geographic: object | None
    domain_geographic: object | None
    domain: object
    flow: object | None
    loaded_data: object | None
    time_grid: object | None


class SpatialSupportProvider(Protocol):
    """Builder contract used by the launcher to materialize support fields."""

    provider_name: ClassVar[str]
    build_phase: ClassVar[Literal["setup", "data"]]

    def required_data_types(self, config: DomainSupportConfig) -> tuple[str, ...]:
        ...

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        ...


class GeneratedBandsSupportProvider:
    provider_name = "generated_bands"
    build_phase = "setup"

    def required_data_types(self, config: DomainSupportConfig) -> tuple[str, ...]:
        _ = config
        return ()

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        if not isinstance(config, GeneratedBandsSupportConfig):
            raise TypeError("generated_bands provider requires GeneratedBandsSupportConfig")
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated bands support requires domain.surface_topo.support")
        support.assert_complete_domain()

        if config.axis == "x":
            lower = float(support.xmin)
            upper = float(support.xmax)
        else:
            lower = float(support.ymin)
            upper = float(support.ymax)
        span = upper - lower
        if span <= 0.0:
            raise ValueError("Domain support extent must be strictly positive")

        if config.coordinate_mode == "relative":
            breaks_abs = [lower + float(value) * span for value in config.breaks]
        else:
            breaks_abs = [float(value) for value in config.breaks]

        if any(value <= lower or value >= upper for value in breaks_abs):
            axis_label = "x" if config.axis == "x" else "y"
            raise ValueError(
                f"Generated bands breaks must lie strictly inside the domain {axis_label} extent "
                f"({lower}, {upper})."
            )

        return GeneratedBandsSupportField(
            identifier=support_id,
            axis=config.axis,
            breaks_abs=breaks_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeneratedRingsSupportProvider:
    provider_name = "generated_rings"
    build_phase = "setup"

    def required_data_types(self, config: DomainSupportConfig) -> tuple[str, ...]:
        _ = config
        return ()

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        if not isinstance(config, GeneratedRingsSupportConfig):
            raise TypeError("generated_rings provider requires GeneratedRingsSupportConfig")
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated rings support requires domain.surface_topo.support")
        support.assert_complete_domain()

        center_x = (
            float(config.center_x)
            if getattr(config, "center_x", None) is not None
            else 0.5 * (float(support.xmin) + float(support.xmax))
        )
        center_y = (
            float(config.center_y)
            if getattr(config, "center_y", None) is not None
            else 0.5 * (float(support.ymin) + float(support.ymax))
        )
        max_radius = min(
            center_x - float(support.xmin),
            float(support.xmax) - center_x,
            center_y - float(support.ymin),
            float(support.ymax) - center_y,
        )
        if max_radius <= 0.0:
            raise ValueError("Generated rings center must lie strictly inside the domain extent.")

        if getattr(config, "coordinate_mode", "relative") == "relative":
            radii_abs = [float(value) * max_radius for value in config.radii]
        else:
            radii_abs = [float(value) for value in config.radii]

        if any(value >= max_radius for value in radii_abs):
            raise ValueError(
                "Generated rings radii must lie strictly inside the largest "
                "inscribed circle around the chosen center."
            )

        return GeneratedRingsSupportField(
            identifier=support_id,
            center_x=center_x,
            center_y=center_y,
            radii_abs=radii_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class CatchmentZonesSupportProvider:
    provider_name = "catchment_zones"
    build_phase = "setup"

    def required_data_types(self, config: DomainSupportConfig) -> tuple[str, ...]:
        _ = config
        return ()

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        if not isinstance(config, CatchmentZonesSupportConfig):
            raise TypeError("catchment_zones provider requires CatchmentZonesSupportConfig")

        domain = context.domain
        source_zone = None
        getter = getattr(domain, "get_zone", None)
        if callable(getter):
            source_zone = getter(config.source_zone_id)
        if source_zone is None:
            zones = getattr(domain, "zones", {})
            source_zone = zones.get(str(config.source_zone_id).strip().lower())
        if source_zone is None:
            raise ValueError(
                f"Catchment support '{support_id}' requires domain zone '{config.source_zone_id}'."
            )

        if not hasattr(source_zone, "encoded_codes") or not hasattr(source_zone, "encoded_to_zone"):
            raise TypeError(
                "Catchment source zone must expose encoded_codes and encoded_to_zone."
            )
        surface_topo = getattr(domain, "surface_topo", None)
        raster_support = getattr(surface_topo, "support", None)
        if not isinstance(raster_support, RasterSupport):
            raise ValueError("Catchment support requires domain.surface_topo.support")

        return RasterZonesSupportField(
            identifier=support_id,
            encoded_codes=np.asarray(source_zone.encoded_codes, dtype=np.int32),
            encoded_to_zone=dict(source_zone.encoded_to_zone),
            raster_support=raster_support,
            nodata_code=int(getattr(source_zone, "nodata_code", 0)),
            source_meta=getattr(source_zone, "source_meta", None),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeologySupportProvider:
    provider_name = "geology"
    build_phase = "data"

    def required_data_types(self, config: DomainSupportConfig) -> tuple[str, ...]:
        _ = config
        return ("geology",)

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        if not isinstance(config, GeologySupportConfig):
            raise TypeError("geology provider requires GeologySupportConfig")

        loaded_data = context.loaded_data
        geology = getattr(loaded_data, "geology", None) if loaded_data is not None else None
        if geology is None:
            raise ValueError(f"Geology support '{support_id}' requires loaded geology data.")
        if str(getattr(geology, "identifier", "")).strip() == str(support_id).strip():
            return geology
        return AliasedSpatialSupportField(identifier=support_id, delegate=geology)


class SpatialSupportProviderRegistry:
    """Registry of named support providers used by the launcher."""

    def __init__(self) -> None:
        self._providers: dict[str, SpatialSupportProvider] = {}

    def register(self, provider: SpatialSupportProvider) -> None:
        self._providers[str(provider.provider_name).strip().lower()] = provider

    def get(self, provider_name: str) -> SpatialSupportProvider:
        normalized = str(provider_name).strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            raise ValueError(f"Unknown spatial support provider '{provider_name}'")
        return provider


def build_default_spatial_support_provider_registry() -> SpatialSupportProviderRegistry:
    """Return the launcher registry populated with the built-in support providers."""
    registry = SpatialSupportProviderRegistry()
    registry.register(GeneratedBandsSupportProvider())
    registry.register(GeneratedRingsSupportProvider())
    registry.register(CatchmentZonesSupportProvider())
    registry.register(GeologySupportProvider())
    return registry
