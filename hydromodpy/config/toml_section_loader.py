"""TOML section orchestration for HydroModPyConfig.from_toml/from_dict."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.analysis.config import AnalysisConfig
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.toml_io.paths import resolve_declared_path
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig

ValidationContext = Literal["toml", "api"]


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into a copy of *base*."""
    result = dict(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _validation_context(raw_context: object) -> ValidationContext:
    if isinstance(raw_context, Mapping) and raw_context.get("validation_context") == "toml":
        return "toml"
    return "api"


def _is_path_field(field_info: FieldInfo) -> bool:
    """
    Return True if the field is typed as ``Path`` or ``Path | None``.
    """
    annotation = field_info.annotation
    if annotation is Path:
        return True
    return Path in getattr(annotation, "__args__", ())


def _input_file_role(field_info: FieldInfo) -> str | None:
    """Return the ``InputFile.role`` annotation attached to a field, if any."""
    from hydromodpy.core.tracking.input_file import InputFile

    for meta in field_info.metadata or ():
        if isinstance(meta, InputFile):
            return meta.role
    return None


def _build_path_fallback_dirs(
    role: str | None,
    workspace_data_dir: Path | None,
) -> list[Path] | None:
    """Build the search path used when a config field is a bare filename.

    Order of fallbacks (each tried only when the bare filename does not
    resolve under the TOML directory):

    1. ``<workspace>/data/<role>/`` - convention-over-configuration:
       data files for variable ``<role>`` live here.
    2. ``<workspace>/data/`` - flat fallback for cross-cutting files.
    """
    if workspace_data_dir is None:
        return None
    fallback: list[Path] = []
    if role:
        fallback.append(workspace_data_dir / role)
    fallback.append(workspace_data_dir)
    return fallback


def _resolve_section_paths(
    data: dict,
    model_cls: type[BaseModel],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> None:
    """
    Resolve relative paths and ``~`` in a config section dict (in-place).

    Bare filenames (no separator, no ``..``) get the convention-driven
    lookup under ``<workspace>/data/<role>/`` when the field carries an
    ``InputFile`` annotation, so users can write
    ``path = "etp_sim2.nc"`` instead of ``../../data/etp/etp_sim2.nc``.
    """
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            role = _input_file_role(field_info)
            fallback_dirs = _build_path_fallback_dirs(role, workspace_data_dir)
            data[field_name] = str(
                resolve_declared_path(
                    value,
                    base_dir=base,
                    fallback_dirs=fallback_dirs,
                )
            )


def load_standard_section(
    section_data: Any,
    model_cls: type[BaseModel],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> BaseModel:
    """Load one regular section by validating against a Pydantic model class."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError(f"TOML section must be a mapping for {model_cls.__name__}")

    payload = dict(section_data)
    _resolve_section_paths(payload, model_cls, base, workspace_data_dir=workspace_data_dir)
    return model_cls.model_validate(payload)


def _raw_declares_dem_source(section_data: Any) -> bool:
    """Return True when raw TOML declares at least one DEM data source."""
    if not isinstance(section_data, Mapping):
        return False
    dem_section = section_data.get("dem")
    if not isinstance(dem_section, Mapping):
        return False
    sources = dem_section.get("sources")
    return isinstance(sources, list) and bool(sources)


_CATCHMENT_VARIANT_BY_KEY: dict[str, str] = {
    "dem": "DemCatchDef",
    "txt": "TxtCatchDef",
    "from_outlet_coord": "OutletCatchDef",
    "from_polyg_shp": "PolygonCatchDef",
}


def _resolve_catchment_paths(
    payload: dict[str, Any],
    base: Path,
    workspace_data_dir: Path | None,
) -> None:
    """Resolve relative paths inside the ``catchment`` block (in-place).

    Mirrors ``_resolve_section_paths`` but operates on the discriminated
    catchment variant identified by ``catch_def``. Legacy flat payloads
    where ``catch_def``/``dem_init_path`` live at the top of the geographic
    section are first folded into a ``catchment`` mapping so the same path
    resolution path applies in both cases.
    """
    from hydromodpy.spatial.geographic import geographic_config as _geo_cfg

    legacy_keys = {
        "catch_def",
        "dem_init_path",
        "cell_size",
        "x_outlet",
        "y_outlet",
        "snap_dist",
        "buff_area",
        "polyg_shp_path",
    }
    legacy_present = legacy_keys.intersection(payload.keys())
    if legacy_present:
        nested = payload.get("catchment")
        merged: dict[str, Any] = dict(nested) if isinstance(nested, Mapping) else {}
        for key in legacy_present:
            value = payload.pop(key)
            if value is None:
                continue
            merged.setdefault(key, value)
        if merged:
            payload["catchment"] = merged

    catchment = payload.get("catchment")
    if not isinstance(catchment, Mapping):
        return
    catch_def = str(catchment.get("catch_def", "")).strip()
    variant_name = _CATCHMENT_VARIANT_BY_KEY.get(catch_def)
    if variant_name is None:
        return
    variant_cls = getattr(_geo_cfg, variant_name)
    catchment_payload = dict(catchment)
    _resolve_section_paths(
        catchment_payload, variant_cls, base, workspace_data_dir=workspace_data_dir
    )
    payload["catchment"] = catchment_payload


def load_geographic_section(
    section_data: Any,
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
    allow_dem_bootstrap: bool = False,
) -> GeographicConfig:
    """Load [geographic], allowing DEM resolution from [data.dem] when declared."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for GeographicConfig")

    payload = dict(section_data)
    _resolve_section_paths(payload, GeographicConfig, base, workspace_data_dir=workspace_data_dir)
    _resolve_catchment_paths(payload, base, workspace_data_dir)
    return GeographicConfig.model_validate(
        payload,
        context={"allow_dem_bootstrap": allow_dem_bootstrap},
    )


def _load_flow_section(section_data: Any, base: Path) -> FlowConfig:
    """Load the flow section using FlowConfig's dedicated parser."""
    if section_data is None:
        section_data = {}
    return FlowConfig.from_toml_section(section_data, base_dir=base)


def _load_data_section(
    section_data: Any,
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> DataManagersConfig:
    """Load the data section with dynamic validation by enabled data types."""
    return DataManagersConfig.from_toml_section(
        section_data,
        base_dir=base,
        workspace_data_dir=workspace_data_dir,
    )


def _load_optional_overview_section(
    section_data: Any,
    base: Path,
) -> OverviewConfig | None:
    """Load the optional ``[overview]`` section."""
    if section_data is None:
        return None
    return load_standard_section(section_data, OverviewConfig, base)


def _load_optional_mesh_catchment_section(
    section_data: Any,
    base: Path,
) -> MeshCatchmentConfig | None:
    """Load the optional ``[mesh_catchment]`` section."""
    if section_data is None:
        return None
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_config_data

    return parse_mesh_catchment_config_data(section_data)


def _load_optional_calibration_section(
    section_data: Any,
    base: Path,
) -> CalibrationConfig | None:
    """Load the optional ``[calibration]`` section."""
    if section_data is None:
        return None
    return load_standard_section(section_data, CalibrationConfig, base)


def _load_optional_analysis_section(
    section_data: Any,
    base: Path,
) -> AnalysisConfig | None:
    """Load the optional ``[analysis]`` section."""
    if section_data is None:
        return None
    if not isinstance(section_data, Mapping):
        raise ValueError("[analysis] must be a mapping")

    from hydromodpy.analysis.batch.config import RegionalLabConfig
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.experiment_config import ComparisonSection

    parsed: dict[str, Any] = {}

    raw_gallery = section_data.get("capability_gallery")
    if raw_gallery is not None:
        parsed["capability_gallery"] = load_standard_section(
            raw_gallery, CapabilityGalleryConfig, base
        )

    raw_batch = section_data.get("batch")
    if raw_batch is not None:
        if not isinstance(raw_batch, Mapping):
            raise ValueError("[analysis.batch] must be a mapping")
        parsed["batch"] = RegionalLabConfig.from_toml(
            raw_batch,
            config_path=base / "analysis_batch.toml",
        )

    raw_comparison = section_data.get("comparison")
    if raw_comparison is not None:
        if not isinstance(raw_comparison, Mapping):
            raise ValueError("[analysis.comparison] must be a mapping")
        parsed["comparison"] = ComparisonSection.model_validate(raw_comparison)

    extra_keys = set(section_data) - {"batch", "capability_gallery", "comparison"}
    if extra_keys:
        unknown = ", ".join(sorted(extra_keys))
        raise ValueError(f"Unknown [analysis] sub-section(s): {unknown}")

    return AnalysisConfig.model_validate(parsed)
