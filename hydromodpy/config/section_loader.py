"""How one raw section becomes its model, with its paths read from the project root.

``HydroModPyConfig._from_payload`` calls these loaders for a TOML file and for a
mapping alike.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.core.config_kit.introspect import named_tables_of
from hydromodpy.core.toml_io.paths import (
    has_url_scheme,
    is_bare_filename,
    resolve_declared_path,
)
from hydromodpy.mesh.mesh_config import MeshConfig

ModelT = TypeVar("ModelT", bound=BaseModel)


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


def _is_an_input_file(field_info: FieldInfo) -> bool:
    """Return True when the field names a file of the user, as ``InputFile`` marks it."""
    from hydromodpy.core.tracking.input_file import InputFile

    return any(isinstance(meta, InputFile) for meta in field_info.metadata or ())


def _resolve_section_paths(
    data: dict[str, Any],
    model_cls: type[BaseModel],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> None:
    """Resolve relative paths and ``~`` in a config section dict (in-place).

    Paths are resolved against ``base`` (the project root / TOML directory)
    without fallback directories. A path starting with a URL scheme is refused
    with ``use source = "url"``.
    """
    for name, table_cls in named_tables_of(model_cls, shipped_only=False).items():
        table = data.get(name)
        if isinstance(table, Mapping):
            data[name] = dict(table)
            _resolve_section_paths(
                data[name], table_cls, base, workspace_data_dir=workspace_data_dir
            )
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            if has_url_scheme(value):
                from hydromodpy.core.exceptions import ConfigError

                raise ConfigError(f"{field_name} '{value}': use source = \"url\"")
            resolved = resolve_declared_path(value, base_dir=base)
            if is_bare_filename(value) and not resolved.exists() and _is_an_input_file(field_info):
                # A bare name used to be looked up in the workspace data
                # folder, under the role of the field then under ``data``.
                # The refusal names where the old fallback had the file, so
                # the user writes one path and runs again.
                from hydromodpy.core.toml_io.paths import (
                    BareInputNameError,
                    bare_name_refusal,
                    former_bare_name_location,
                )

                raise BareInputNameError(
                    bare_name_refusal(
                        value,
                        former=former_bare_name_location(
                            value, workspace_data_dir, role=_input_file_role(field_info)
                        ),
                    )
                )
            data[field_name] = str(resolved)


def load_standard_section(
    section_data: Any,
    model_cls: type[ModelT],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
    context: Mapping[str, Any] | None = None,
) -> ModelT:
    """Load one regular section by validating against a Pydantic model class."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError(f"TOML section must be a mapping for {model_cls.__name__}")

    payload = dict(section_data)
    _resolve_section_paths(payload, model_cls, base, workspace_data_dir=workspace_data_dir)
    return model_cls.model_validate(payload, context=context)


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
    catchment variant identified by ``kind``.
    """
    from hydromodpy.catchment.preprocess import catchment_config as _geo_cfg

    catchment = payload.get("catchment")
    if not isinstance(catchment, Mapping):
        return
    catch_def = str(catchment.get("kind", "")).strip()
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


def load_optional_section(section_data: Any, model_cls: type[ModelT], base: Path) -> ModelT | None:
    """Load an optional section like a regular one; an absent section stays ``None``."""
    if section_data is None:
        return None
    return load_standard_section(section_data, model_cls, base)


def _load_optional_mesh_section(
    section_data: Any,
    base: Path,
) -> MeshConfig | None:
    """Load the optional ``[mesh]`` section.

    The file named by ``[mesh.triangle] path`` is resolved against the TOML
    directory, like every other declared path.
    """
    if section_data is None:
        return None
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for MeshConfig")
    payload = dict(section_data)
    triangle = payload.get("triangle")
    if isinstance(triangle, Mapping) and isinstance(triangle.get("path"), str):
        payload["triangle"] = {
            **triangle,
            "path": str(resolve_declared_path(triangle["path"], base_dir=base)),
        }
    return MeshConfig.model_validate(payload)


def _load_optional_calibration_section(
    section_data: Any,
    base: Path,
    *,
    sealed: bool = False,
) -> CalibrationConfig | None:
    """Load the optional ``[calibration]`` section, which a sealed run reads more widely."""
    if section_data is None:
        return None
    context = {"validation_context": "snapshot"} if sealed else None
    return load_standard_section(section_data, CalibrationConfig, base, context=context)
