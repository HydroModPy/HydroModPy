from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.domain.surfaces import Surfaces


class Domain:
    """
    Domain object holding geometry and thematic zones.

    Members:
    - `surface`
    - `substratum`
    - `zones`
    - `georeferencing`
    """

    def __init__(
        self,
        config: DomainConfig | Mapping[str, object] | None = None,
        *,
        geographic: object | None = None,
    ):
        self.config = self._coerce_config(config)
        self.surface: Surfaces | None = None
        self.substratum: Surfaces | None = None
        self.zones: dict[str, object] = {}
        self.georeferencing = self._build_georeferencing(geographic)

        self._load_declared_zones(
            geographic=geographic,
        )

    @staticmethod
    def _coerce_config(
        config: DomainConfig | Mapping[str, object] | None,
    ) -> DomainConfig:
        if config is None:
            return DomainConfig()
        if isinstance(config, DomainConfig):
            return config
        if not isinstance(config, Mapping):
            raise TypeError("Domain config must be a DomainConfig instance or a mapping")
        return DomainConfig.model_validate(dict(config))

    @staticmethod
    def _build_georeferencing(geographic: object | None) -> dict[str, object]:
        if geographic is None:
            return {}

        mapping = {
            "crs": "crs_proj",
            "resolution": "dem_res",
            "xmin": "xmin",
            "xmax": "xmax",
            "ymin": "ymin",
            "ymax": "ymax",
        }
        out: dict[str, object] = {}
        for key, attr_name in mapping.items():
            if hasattr(geographic, attr_name):
                out[key] = getattr(geographic, attr_name)
        return out

    def _load_declared_zones(
        self,
        *,
        geographic: object | None,
    ) -> None:
        for zone_id in self.config.zone_ids:
            if zone_id == "geology":
                self.zones["geology"] = self._build_geology_zone(
                    geographic=geographic,
                    geology_config=self.config.geology,
                )
                continue
            raise ValueError(f"Unsupported domain zone id: '{zone_id}'")

    @staticmethod
    def _build_geology_zone(
        *,
        geographic: object | None,
        geology_config: object | Mapping[str, object] | None,
    ) -> object:
        if geographic is None:
            raise ValueError("domain.zone_ids includes 'geology' but geographic is missing")

        from hydromodpy.data_managers.geology.geology_field import GeologyField
        from hydromodpy.watershed.geology_config import GeologyConfig

        if geology_config is None:
            geology_cfg = GeologyConfig()
        elif isinstance(geology_config, GeologyConfig):
            geology_cfg = geology_config
        elif isinstance(geology_config, Mapping):
            geology_cfg = GeologyConfig.model_validate(dict(geology_config))
        else:
            raise TypeError(
                "geology_config must be a GeologyConfig instance, mapping, or None"
            )

        if bool(geology_cfg.landsea):
            raise ValueError(
                "Domain GeologyField pipeline does not support legacy landsea=True flag. "
                "Please use landsea=None/false."
            )

        source_rel = Path(str(geology_cfg.types_obs))
        source_path = (
            source_rel
            if source_rel.is_absolute()
            else (Path(geology_cfg.geo_path) / source_rel)
        )

        reference_raster_path = (
            getattr(geographic, "watershed_buff_dem", None)
            or getattr(geographic, "watershed_box_buff_dem", None)
            or getattr(geographic, "watershed_dem", None)
        )
        if reference_raster_path is None:
            raise ValueError(
                "Cannot build geology field: geographic object has no watershed DEM path "
                "(expected one of watershed_buff_dem / watershed_box_buff_dem / watershed_dem)."
            )

        payload: dict[str, object] = {
            "id": str(geology_cfg.id),
            "source": {
                "path": str(source_path),
                "kind": "auto",
                "code_field": str(geology_cfg.fields_obs),
                "reference_raster_path": str(reference_raster_path),
                "all_touched": False,
            },
            "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
        }

        clip_path = getattr(geographic, "watershed_shp", None)
        if clip_path is not None:
            payload["clip_polygon_path"] = str(clip_path)

        return GeologyField.from_dict(payload)
