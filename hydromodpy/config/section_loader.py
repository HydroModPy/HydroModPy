"""How a raw document becomes its validated sections, with every fault it holds.

The loader of a file and the check of a document walk the same steps here, so
there is one validator. The resolutions run first on the raw document: the
protocol of a calibration, the defaults ``[site]`` and ``[metrics]`` give to
``[calibration]``, the retired and unknown sections, the project root of
``[workspace]``. Then each section of ``SECTIONS`` is validated on its own, and a
fault of one section does not stop the next. Each fault gives its diagnostics, a
required key not written yet among them, and the exception the loader raised for
it alone, so the loader raises the first fault in the order it always did and
the check returns them all. The rules that read several sections together run
on the built document (``config/cross_checks.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeVar, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from hydromodpy.calibration.config import CalibrationConfig, apply_project_defaults
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.config_migration import _raw_flow_process_solver
from hydromodpy.config.cross_checks import RuleOutcome, run_cross_rules
from hydromodpy.core.config_kit.introspect import (
    fields_and_tables,
    is_union_origin,
    named_tables_of,
)
from hydromodpy.core.diagnostic import Diagnostic, Severity
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError, HydroModPyError
from hydromodpy.core.toml_io.error_locator import (
    format_loc,
    format_validation_error,
    json_pointer,
    located_faults,
)
from hydromodpy.core.toml_io.paths import (
    has_url_scheme,
    is_bare_filename,
    resolve_declared_path,
)
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data import DataManagersConfig
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial_config import SpinupConfig
from hydromodpy.model.transport.transport_config import TransportConfig
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.solver.base.observation_config import ObservationConfig
from hydromodpy.solver.base.simulation_config import SimulationConfig
from hydromodpy.solver.base.solver_config import SolverConfig, backend_following_the_process

ModelT = TypeVar("ModelT", bound=BaseModel)

# ---------------------------------------------------------------------------
# One raw section to its model, paths read from the project root
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The retired root sections
# ---------------------------------------------------------------------------

ANALYSIS_SECTION_REFUSAL = (
    "[analysis] was removed: a comparison is hmp report compare over sealed runs, "
    "figures are hmp export <run> --regen figures on a run"
)
HYDROMETRY_SECTION_REFUSAL = (
    "a root [hydrometry] is not read: a run reads its stations from [data.hydrometry]"
)
TESTBED_REFUSAL = (
    "a case of a testbed is a recipe: list the catchments in [sites] and the "
    "variants in [sites.recipes]."
)
_ROOT_PERSISTENCE_REFUSAL = (
    "Section [persistence] is not read by any run. Write its keys under "
    "[simulation.results.persistence], which a run reads, and so does the run "
    "a calibration promotes."
)
_RETIRED_MESH_SECTIONS: dict[str, str] = {
    "mesh_catchment": (
        'Section [mesh_catchment] is replaced by [mesh]. Write engine = "triangle" or '
        '"voronoi" (the cells MODFLOW 6 ran on were chosen by sgrid.grid_dual), '
        "cell_size (was zone_meshing.global_size), river_cell_size and river_band (were "
        "zone_meshing.interface_size and interface_distance) and [mesh.families] (was "
        "constraints_mode and watershed_boundary). The cache, output, figure, "
        "hydraulic_properties and rivers keys are gone: the run caches its mesh and "
        "reads K from [flow.param.K]."
    ),
    "mesh_catchment_batch": (
        "Section [mesh_catchment_batch] has no replacement: [mesh] meshes the catchment "
        "of the project."
    ),
    "mesh_input": (
        'Section [mesh_input] is replaced by [mesh.triangle] path, with engine = "triangle" '
        'or "voronoi" in [mesh]. '
        "Its bundle_dir has no replacement."
    ),
}

RETIRED_SECTIONS: dict[str, str] = {
    "initializing": "Section [initializing] is no longer supported. Use [workspace] instead.",
    "modflow": (
        "Section [modflow] is no longer supported. "
        "Use [solver], whose table for each flow solver sits under its name."
    ),
    "capability_gallery": (
        "Section [capability_gallery] is no longer supported: the figures of "
        "a run are drawn again by hmp export <run> --regen figures."
    ),
    "analysis": ANALYSIS_SECTION_REFUSAL,
    "hydrometry": HYDROMETRY_SECTION_REFUSAL,
    "batch": (
        "Section [batch] is no longer supported. List the catchments in [sites] "
        "and the variants in [sites.recipes]."
    ),
    "testbed": "Section [testbed] is no longer supported: " + TESTBED_REFUSAL,
    "persistence": _ROOT_PERSISTENCE_REFUSAL,
    **_RETIRED_MESH_SECTIONS,
    "regional_lab": (
        "Section [regional_lab] is not a HydroModPyConfig section. A regional "
        "lab is a [sites] project: list the catchments in [sites] and the "
        "variants in [sites.recipes]."
    ),
}
"""Root sections a file may no longer write, each with the sentence that refuses it.

A new retired section is one row here. The loader and the check refuse each one
a document writes, and a direct ``model_validate`` refuses the first.
"""


def retired_section(data: Mapping[str, Any]) -> str | None:
    """Return the first retired root section a document declares, or None."""
    return next((name for name in RETIRED_SECTIONS if name in data), None)


# ---------------------------------------------------------------------------
# The codes of a diagnostic
# ---------------------------------------------------------------------------

PYDANTIC_CODES: dict[str, str] = {
    "union_tag_not_found": "to_fill",
    "extra_forbidden": "unknown_key",
    "unexpected_keyword_argument": "unknown_key",
    "unexpected_positional_argument": "unknown_key",
    "no_such_attribute": "unknown_key",
    "invalid_key": "unknown_key",
    "literal_error": "not_a_choice",
    "enum": "not_a_choice",
    "union_tag_invalid": "not_a_choice",
    "multiple_of": "out_of_range",
    "finite_number": "out_of_range",
    "too_short": "out_of_range",
    "too_long": "out_of_range",
    "string_too_short": "out_of_range",
    "string_too_long": "out_of_range",
    "bytes_too_short": "out_of_range",
    "bytes_too_long": "out_of_range",
    "int_parsing_size": "out_of_range",
    "decimal_max_digits": "out_of_range",
    "decimal_max_places": "out_of_range",
    "decimal_whole_digits": "out_of_range",
    "date_past": "out_of_range",
    "date_future": "out_of_range",
    "datetime_past": "out_of_range",
    "datetime_future": "out_of_range",
    "url_too_long": "out_of_range",
    "model_attributes_type": "wrong_type",
    "string_sub_type": "wrong_type",
    "string_unicode": "wrong_type",
    "string_pattern_mismatch": "wrong_type",
    "string_not_ascii": "wrong_type",
    "int_from_float": "wrong_type",
    "bytes_invalid_encoding": "wrong_type",
    "set_item_not_hashable": "wrong_type",
    "json_invalid": "wrong_type",
    "none_required": "wrong_type",
    "is_instance_of": "wrong_type",
    "is_subclass_of": "wrong_type",
    "timezone_naive": "wrong_type",
    "timezone_aware": "wrong_type",
    "timezone_offset": "wrong_type",
    "date_from_datetime_inexact": "wrong_type",
    "datetime_object_invalid": "wrong_type",
    "url_syntax_violation": "wrong_type",
    "url_scheme": "wrong_type",
    "uuid_version": "wrong_type",
    "needs_python_object": "wrong_type",
    "value_error": "refused_value",
    "assertion_error": "refused_value",
}
"""The check code of a Pydantic error type, beside three rules on its name.

A type that starts with ``missing`` is ``to_fill``, one that starts with
``greater_than`` or ``less_than`` is ``out_of_range``, one that ends with
``_type`` or ``_parsing`` is ``wrong_type``. Any other type is ``refused_value``,
so a type a new Pydantic adds never gives a code outside the closed set.
"""

RETIRED_KEY_MARKERS: tuple[str, ...] = (
    "not accepted any more",
    "was removed in",
    "is a bare name",
    "written by a pre-release of 2.0",
)
"""The words of the four refusals of a form a release retired.

Their raisers are not typed: ``_refuse_removed_keys`` of the model base, a move of
the migration, the refusal of a bare input name, and the refusal of a key only a
pre-release of 2.0 wrote (``prerelease_refusal`` of ``schema/changes.py``). A fault
whose text holds one of them is ``retired_key``.
"""

UNKNOWN_NAME_MARKER = ", and this installation serves "
"""The words of ``check_registered_name`` in ``core/plugin_registry.py``.

A name refused by a registry is a ``value_error`` to Pydantic, and these words
tell it from another refused value.
"""

_WARNING_CODES = frozenset({"old_key", "cross_warning", "section_warning", "experimental_key"})


def code_of(error_type: str, detail: str = "") -> str:
    """Return the check code of a fault, from its Pydantic type and its text."""
    if any(marker in detail for marker in RETIRED_KEY_MARKERS):
        return "retired_key"
    if error_type == "value_error" and UNKNOWN_NAME_MARKER in detail:
        return "unknown_name"
    code = PYDANTIC_CODES.get(error_type)
    if code is not None:
        return code
    if error_type.startswith("missing"):
        return "to_fill"
    if error_type.startswith(("greater_than", "less_than")):
        return "out_of_range"
    if error_type.endswith(("_type", "_parsing")):
        return "wrong_type"
    return "refused_value"


def severity_of(code: str) -> Severity:
    """Return the severity a code has before ``partial=False`` reads it."""
    if code == "to_fill":
        return "to_fill"
    if code in _WARNING_CODES:
        return "warning"
    return "error"


# ---------------------------------------------------------------------------
# The models a path crosses: help of a key, required keys not written
# ---------------------------------------------------------------------------


def _unwrap(annotation: Any) -> tuple[list[Any], str | None]:
    """Return the types *annotation* admits, ``None`` dropped, and its discriminator."""
    discriminator: str | None = None
    members: list[Any] = []
    pending = [annotation]
    while pending:
        node = pending.pop(0)
        origin = get_origin(node)
        if origin is Annotated:
            inner, *metadata = get_args(node)
            for meta in metadata:
                tag = getattr(meta, "discriminator", None)
                tag = getattr(tag, "discriminator", tag)
                if isinstance(tag, str):
                    discriminator = tag
            pending.insert(0, inner)
        elif is_union_origin(origin):
            pending[0:0] = [arg for arg in get_args(node) if arg is not type(None)]
        elif node is not type(None):
            members.append(node)
    return members, discriminator


def _container(annotation: Any) -> tuple[str, Any] | None:
    """Return ``("dict", value type)`` or ``("list", item type)`` for a container."""
    origin = get_origin(annotation)
    if not isinstance(origin, type):
        return None
    args = get_args(annotation)
    if issubclass(origin, Mapping) and len(args) == 2:
        return "dict", args[1]
    if issubclass(origin, (list, tuple, set, frozenset, Sequence)) and args:
        return "list", args[0]
    return None


def _is_model(node: Any) -> bool:
    return isinstance(node, type) and issubclass(node, BaseModel)


def _variant(models: Sequence[type[BaseModel]], tag: str, value: Any) -> type[BaseModel] | None:
    """Return the variant of a discriminated union whose tag field admits *value*."""
    for model in models:
        tag_field = model.model_fields.get(tag)
        if tag_field is None:
            continue
        literals, _ = _unwrap(tag_field.annotation)
        admitted = {arg for literal in literals for arg in get_args(literal)}
        if value in admitted:
            return model
    return None


def _field_of(model: type[BaseModel], key: str) -> FieldInfo | None:
    """Return the field *key* of *model*, or the named table it holds under *key*."""
    found = model.model_fields.get(key)
    if found is not None:
        return found
    if getattr(model, "named_tables", None) is None:
        return None
    # A table named by a plugin, [solver.<name>]: its settings class is the
    # one the registry serves, so a plugin without a phrase of its own gives
    # the docstring of its fields as help.
    return fields_and_tables(model, shipped_only=False).get(key)


def field_at(root: type[BaseModel], parts: Sequence[str]) -> FieldInfo | None:
    """Return the field a path names, through unions, mappings and lists, or None.

    A segment after a mapping of models is a key the user chose (a parameter id,
    a boundary name), and a digit after a list is an index: the walk crosses
    them to the type of the value. A path that stops on such a key gives the
    field of the mapping.
    """
    candidates: list[Any] = [root]
    found: FieldInfo | None = None
    for part in parts:
        step: list[Any] = []
        step_field: FieldInfo | None = None
        for candidate in candidates:
            for member in _unwrap(candidate)[0]:
                container = _container(member)
                if container is not None:
                    step.append(container[1])
                    continue
                if not _is_model(member):
                    continue
                info = _field_of(member, part)
                if info is not None and step_field is None:
                    step_field = info
                    step.append(info.annotation)
        if not step:
            return None
        candidates = step
        if step_field is not None:
            found = step_field
    return found


def help_at(root: type[BaseModel], parts: Sequence[str]) -> str:
    """Return the description of the field a path names, ``""`` when it has none."""
    info = field_at(root, parts)
    return (info.description or "") if info is not None else ""


def _written(model: type[BaseModel], name: str, info: FieldInfo, value: Mapping[str, Any]) -> bool:
    """Whether *value* writes the field *name*, by its name, its alias or an old spelling."""
    if name in value or (isinstance(info.alias, str) and info.alias in value):
        return True
    legacy = getattr(model, "model_legacy_keys", None) or {}
    return any(old in value for old, new in legacy.items() if new == name)


def missing_keys(
    annotation: Any, value: Any, at: tuple[str, ...], discriminator: str | None = None
) -> Iterator[tuple[str, ...]]:
    """Yield the path of each required key *value* leaves out, walked along *annotation*.

    Across a discriminated union, a missing tag is the key to fill and the
    fields of the variants are not walked. Across a mapping of models, the key
    the user chose is crossed to its value. A union of several models without a
    tag is not walked, since nothing says which one the document means.
    """
    members, tag = _unwrap(annotation)
    tag = discriminator or tag
    models = [member for member in members if _is_model(member)]
    if isinstance(value, Mapping):
        containers = [_container(member) for member in members]
        mapped = next((item for kind, item in filter(None, containers) if kind == "dict"), None)
        if mapped is not None and not models:
            for key, item in value.items():
                yield from missing_keys(mapped, item, (*at, str(key)))
            return
        if tag is not None and len(models) > 1:
            if tag not in value:
                yield (*at, tag)
                return
            chosen = _variant(models, tag, value[tag])
            models = [chosen] if chosen is not None else []
        if len(models) != 1:
            return
        model = models[0]
        for name, info in model.model_fields.items():
            if not _written(model, name, info, value):
                if info.is_required():
                    yield (*at, name)
                continue
            key = name if name in value else str(info.alias)
            yield from missing_keys(info.annotation, value[key], (*at, key), info.discriminator)
        if getattr(model, "named_tables", None) is not None:
            for key, item in value.items():
                if key in model.model_fields or not isinstance(item, Mapping):
                    continue
                table = named_tables_of(model, shipped_only=False).get(key)
                if table is not None:
                    yield from missing_keys(table, item, (*at, key))
        return
    if isinstance(value, list):
        for member in members:
            container = _container(member)
            if container is not None and container[0] == "list":
                for index, item in enumerate(value):
                    yield from missing_keys(container[1], item, (*at, str(index)))
                return


def _fold_into_to_fill(
    diagnostics: list[Diagnostic], holes: Sequence[tuple[str, ...]], root: type[BaseModel]
) -> list[Diagnostic]:
    """Merge each fault at or above a required key not written into its ``to_fill``.

    Pydantic does not say "missing" for every key left out: a union without its
    tag says ``union_tag_not_found``, a validator of the table says
    ``value_error`` at the table. A fault whose path is the hole or one of its
    parents is folded into the hole, its text kept in ``detail``. A hole that
    folds no fault is not reported, since a validator before may have filled it.
    """
    folded: dict[int, list[Diagnostic]] = {}
    absorbed: set[int] = set()
    for hole in holes:
        under = [
            index
            for index, diagnostic in enumerate(diagnostics)
            if diagnostic.severity != "warning"
            and diagnostic.parts
            and diagnostic.parts == hole[: len(diagnostic.parts)]
        ]
        if not under:
            continue
        absorbed.update(under)
        detail = "; ".join(dict.fromkeys(diagnostics[index].detail for index in under))
        line = next((diagnostics[i].line_number for i in under if diagnostics[i].line_number), None)
        folded.setdefault(min(under), []).append(
            Diagnostic(
                path=format_loc(hole),
                code="to_fill",
                severity="to_fill",
                detail=detail,
                help=help_at(root, hole),
                line_number=line,
                keys=hole,
                error_type="missing",
            )
        )
    result: list[Diagnostic] = []
    for index, diagnostic in enumerate(diagnostics):
        result.extend(folded.get(index, ()))
        if index not in absorbed:
            result.append(diagnostic)
    return result


# ---------------------------------------------------------------------------
# A fault, its diagnostics, and the exception the loader raises for it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fault:
    """One refusal of a document: what it says, and what the loader raised for it alone."""

    diagnostics: tuple[Diagnostic, ...]
    error: Exception


def diagnostics_of(
    error: ValidationError,
    *,
    root: type[BaseModel],
    loc_prefix: Sequence[str] = (),
    document: Any = None,
    source_path: Path | None = None,
) -> list[Diagnostic]:
    """Return one diagnostic per fault of a Pydantic error, at the key the document wrote."""
    diagnostics: list[Diagnostic] = []
    for parts, record in located_faults(
        error, loc_prefix=loc_prefix, source_path=source_path, document=document
    ):
        error_type = str(record.get("type", ""))
        detail = str(record.get("msg", ""))
        code = code_of(error_type, detail)
        line = record.get("line")
        diagnostics.append(
            Diagnostic(
                path=format_loc(parts),
                code=code,
                severity=severity_of(code),
                detail=detail,
                help=help_at(root, parts),
                line_number=line if isinstance(line, int) else None,
                keys=tuple(parts),
                error_type=error_type,
            )
        )
    return diagnostics


def section_refusal(
    section: str,
    message: str,
    *,
    source_path: Path | None = None,
    error_type: str = "extra_forbidden",
) -> ConfigValidationError:
    """Build the refusal of one named top-level section, pointer included.

    A section a document is not allowed to declare is a fault of that document,
    not of this process, so it carries the same shape as a Pydantic field fault
    and reaches the same exit code.
    """
    return ConfigValidationError(
        f"{source_path}: {message}" if source_path is not None else message,
        details=(
            {
                "pointer": json_pointer((section,)),
                "loc": section,
                "msg": message,
                "type": error_type,
            },
        ),
        source=None if source_path is None else str(source_path),
    )


def validation_refusal(
    exc: ValidationError,
    *,
    loc_prefix: Sequence[str] = (),
    source_path: Path | None = None,
    document: Mapping[str, Any] | None = None,
) -> ConfigValidationError:
    """Turn a Pydantic failure into the typed refusal the loader raises.

    ``loc_prefix`` is what makes the JSON Pointer true. A section is validated
    against its own model, so Pydantic reports ``dem_correction_type`` where the
    document says ``geographic.dem_correction_type``; without the prefix the
    pointer would name a root key that does not exist.

    ``document`` is the mapping that was validated, and it is what settles the
    other half: Pydantic inserts the tag of the union variant it chose, and the
    document is the only thing that knows that segment is not a key of its own.
    """
    from hydromodpy.core.toml_io.error_locator import validation_error_details

    return ConfigValidationError(
        format_validation_error(
            exc, source_path=source_path, loc_prefix=loc_prefix, document=document
        ),
        details=validation_error_details(
            exc, loc_prefix=loc_prefix, source_path=source_path, document=document
        ),
        source=None if source_path is None else str(source_path),
    )


def _section_fault(
    section: str,
    message: str,
    *,
    error_type: str,
    code: str | None = None,
    root: type[BaseModel],
    source_path: Path | None,
    keys: tuple[str, ...] | None = None,
) -> Fault:
    """Return the fault of a refusal written by hand, at *keys* or at the section."""
    where = keys or (section,)
    code = code or code_of(error_type, message)
    error = section_refusal(section, message, source_path=source_path, error_type=error_type)
    if keys is not None:
        error = ConfigValidationError(
            str(error),
            details=(
                {
                    "pointer": json_pointer(where),
                    "loc": format_loc(where),
                    "msg": message,
                    "type": error_type,
                },
            ),
            source=error.source,
        )
    diagnostic = Diagnostic(
        path=format_loc(where),
        code=code,
        severity=severity_of(code),
        detail=message,
        help=help_at(root, where),
        keys=where,
        error_type=error_type,
    )
    return Fault((diagnostic,), error)


def _typed_fault(section: str, exc: HydroModPyError, root: type[BaseModel]) -> Fault:
    """Return the fault of a typed refusal a loader raised, at its section."""
    detail = exc.message or str(exc)
    code = code_of("", detail)
    diagnostic = Diagnostic(
        path=section,
        code=code,
        severity=severity_of(code),
        detail=detail,
        help=help_at(root, (section,)) if section else "",
        keys=(section,) if section else (),
    )
    return Fault((diagnostic,), exc)


def raise_the_first(faults: Sequence[Fault]) -> NoReturn:
    """Raise the error of the first fault, carrying the diagnostics of them all.

    The type of the error, and so the exit code, is the one the loader raised
    when it stopped at the first fault. The message names every fault.
    """
    first = faults[0].error
    # The loader reads a document to run it, so a key not written yet is an error.
    diagnostics = [
        diagnostic.with_severity("error") if diagnostic.severity == "to_fill" else diagnostic
        for fault in faults
        for diagnostic in fault.diagnostics
    ]
    if isinstance(first, HydroModPyError):
        message = None
        if len(faults) > 1:
            message = "\n".join(
                getattr(fault.error, "message", "") or str(fault.error) for fault in faults
            )
        raise first.carrying(diagnostics, message=message)
    raise first


# ---------------------------------------------------------------------------
# The resolutions, on the raw document
# ---------------------------------------------------------------------------


def with_calibration_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    """Write ``[site] gauge`` and ``[metrics] window`` into ``[calibration]``.

    The defaults the calibration runners apply
    (:func:`~hydromodpy.calibration.config.apply_project_defaults`), applied
    here too, so a document that leaves ``observes`` or ``window`` to the
    project loads the same way through the loader and the check. A written
    station that is not the gauge raises :class:`ConfigError`.
    """
    calibration = raw.get("calibration")
    if not isinstance(calibration, Mapping):
        return raw
    site, metrics = raw.get("site"), raw.get("metrics")
    raw["calibration"] = apply_project_defaults(
        calibration,
        site_gauge=site.get("gauge") if isinstance(site, Mapping) else None,
        metrics_window=metrics.get("window") if isinstance(metrics, Mapping) else None,
    )
    return raw


def align_solver_keys(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Make ``solver.backend`` and the flow process name one solver.

    The run builds the solver the flow process names, and the checks read
    ``solver.backend``. When the document writes only the process, the backend
    follows it. When it writes both with two names, it is refused. ``data``
    holds ``simulation`` and ``solver``, raw or validated.

    Raises
    ------
    ValueError
        When ``solver.backend`` and the flow process name two solvers.
    """
    flow = _raw_flow_process_solver(data.get("simulation"))
    if flow is None:
        return data
    process_id, process_solver = flow
    solver = data.get("solver")
    if isinstance(solver, SolverConfig):
        declared = "backend" in solver.model_fields_set
        backend = solver.backend if declared else None
    elif isinstance(solver, Mapping):
        declared = "backend" in solver
        backend = solver.get("backend")
    elif solver is None:
        declared, backend = False, None
    else:
        return data
    if declared:
        backend_solver = backend.strip().lower() if isinstance(backend, str) else None
        if backend_solver and backend_solver != process_solver.lower():
            raise ValueError(
                f"solver.backend names {backend_solver!r} and the flow process "
                f"{process_id!r} of [[simulation.process]] names {process_solver!r} in "
                "solvers. The run builds the solver of the process and the checks "
                "read solver.backend, so both must name the same solver. Write the "
                "same name in both, or remove solver.backend: it then follows the "
                "flow process."
            )
        return data
    # The derived name is marked, so it stays out of the fields set and a
    # later assignment of another flow solver moves it again.
    payload = dict(data)
    derived = backend_following_the_process(process_solver)
    if isinstance(solver, SolverConfig):
        # A copy is not validated again, so its fields set is kept here.
        following = solver.model_copy(update={"backend": derived})
        following.__pydantic_fields_set__.discard("backend")
        payload["solver"] = following
    else:
        payload["solver"] = {**(solver or {}), "backend": derived}
    return payload


@dataclass
class Resolved:
    """A raw document after its resolutions, with the faults they found.

    ``skipped`` names the sections a resolution refused: they are not validated
    again, so their fault is told once.
    """

    raw: dict[str, Any]
    workspace: dict[str, Any]
    allow_dem_bootstrap: bool
    faults: list[Fault] = field(default_factory=list)
    skipped: set[str] = field(default_factory=set)


def resolve_document(
    root: type[BaseModel],
    document: dict[str, Any],
    *,
    base: Path,
    forced_root: Path | None,
    in_a_file: bool,
    source_path: Path | None = None,
) -> Resolved:
    """Apply the resolutions of the raw document, in the order the loader always did.

    The protocol of a calibration is expanded, ``[site]`` and ``[metrics]`` give
    their defaults to ``[calibration]``, each retired and each unknown root
    section is refused, and ``[workspace]`` gets its project root: *forced_root*
    when given, else the one the document writes, else *base*. *in_a_file*
    refuses a project root written in a file.
    """
    faults: list[Fault] = []
    skipped: set[str] = set()
    try:
        raw = expand_calibration_protocol(document)
    except ValidationError as exc:
        # Pydantic's ValidationError IS a ValueError, so this clause comes first: a
        # protocol validating its own options would otherwise be pointed at the
        # whole [calibration] table as a raw Pydantic dump.
        prefix = ("calibration", "protocol")
        faults.append(
            Fault(
                tuple(
                    diagnostics_of(
                        exc,
                        root=root,
                        loc_prefix=prefix,
                        document=document,
                        source_path=source_path,
                    )
                ),
                validation_refusal(
                    exc, loc_prefix=prefix, source_path=source_path, document=document
                ),
            )
        )
        raw, skipped = document, {"calibration"}
    except ValueError as exc:
        faults.append(
            _section_fault(
                "calibration",
                str(exc),
                error_type="value_error",
                root=root,
                source_path=source_path,
            )
        )
        raw, skipped = document, {"calibration"}
    if "calibration" not in skipped:
        try:
            raw = with_calibration_defaults(raw)
        except ConfigError as exc:
            faults.append(
                _section_fault(
                    "calibration",
                    str(exc),
                    error_type="value_error",
                    root=root,
                    source_path=source_path,
                )
            )
            skipped.add("calibration")
    for name in RETIRED_SECTIONS:
        if name in raw:
            faults.append(
                _section_fault(
                    name,
                    RETIRED_SECTIONS[name],
                    error_type="extra_forbidden",
                    code="retired_section",
                    root=root,
                    source_path=source_path,
                )
            )
    unknown = sorted(set(raw) - set(root.model_fields) - set(RETIRED_SECTIONS))
    if unknown:
        faults.append(_unknown_sections(unknown, source_path=source_path))

    workspace = raw.get("workspace", {})
    if workspace is None:
        workspace = {}
    if not isinstance(workspace, Mapping):
        faults.append(
            _section_fault(
                "workspace",
                "TOML section [workspace] must be a mapping",
                error_type="dict_type",
                root=root,
                source_path=source_path,
            )
        )
        workspace = {}
    workspace = dict(workspace)
    if in_a_file and "project_root" in workspace:
        faults.append(
            _section_fault(
                "workspace",
                "[workspace] project_root is not a key of a file: the project root is "
                "the folder that holds project.toml (or the folder of this file). "
                "Delete the line.",
                error_type="extra_forbidden",
                root=root,
                source_path=source_path,
                keys=("workspace", "project_root"),
            )
        )
        workspace.pop("project_root")
    if forced_root is not None:
        workspace["project_root"] = str(forced_root)
    elif not workspace.get("project_root"):
        workspace["project_root"] = str(base)

    geographic = raw.get("geographic", {})
    allow_dem_bootstrap = isinstance(geographic, Mapping) and _raw_declares_dem_source(
        raw.get("data", {})
    )
    return Resolved(raw, workspace, allow_dem_bootstrap, faults, skipped)


def _unknown_sections(names: Sequence[str], *, source_path: Path | None) -> Fault:
    """Return the one fault that names every unknown root section."""
    message = f"Unknown top-level TOML section(s): {', '.join(names)}"
    diagnostics = tuple(
        Diagnostic(
            path=name,
            code="unknown_key",
            severity="error",
            detail="Extra inputs are not permitted",
            keys=(name,),
            error_type="extra_forbidden",
        )
        for name in names
    )
    error = ConfigValidationError(
        f"{source_path}: {message}" if source_path is not None else message,
        source=None if source_path is None else str(source_path),
        diagnostics=diagnostics,
    )
    return Fault(diagnostics, error)


# ---------------------------------------------------------------------------
# The sections, one by one
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionContext:
    """What a section loader reads besides its own table."""

    root: type[BaseModel]
    base: Path
    workspace_data_dir: Path | None = None
    allow_dem_bootstrap: bool = False
    sealed: bool = False


ABSENT: Any = object()
"""The default of a section that is not handed to the root when the document leaves it out."""


@dataclass(frozen=True)
class Section:
    """How one root section is validated.

    ``default`` is what the loader reads when the document leaves the section out.
    A ``required`` section left out is ``to_fill``. ``mapping_refusal`` refuses a
    section that is not a table, before its loader runs.
    """

    loader: Callable[[Any, SectionContext], Any]
    default: Any
    required: bool = False
    mapping_refusal: str | None = None


def _standard(model_cls: type[BaseModel]) -> Callable[[Any, SectionContext], Any]:
    return lambda data, ctx: load_standard_section(
        data, model_cls, ctx.base, workspace_data_dir=ctx.workspace_data_dir
    )


def _optional(model_cls: type[BaseModel]) -> Callable[[Any, SectionContext], Any]:
    return lambda data, ctx: load_optional_section(data, model_cls, ctx.base)


def _as_written(name: str) -> Callable[[Any, SectionContext], Any]:
    """Validate a section that names no file against the model of its root field.

    Its relative paths, if any, are read from the project root by the code that
    opens them, not rebased here.
    """

    def load(data: Any, ctx: SectionContext) -> Any:
        if data is None:
            return None
        models = [member for member in _unwrap(ctx.root.model_fields[name].annotation)[0]]
        return models[0].model_validate(data)

    return load


SECTIONS: dict[str, Section] = {
    "workspace": Section(
        lambda data, ctx: load_standard_section(data, WorkspaceConfig, ctx.base),
        default={},
        required=True,
    ),
    "geographic": Section(
        lambda data, ctx: load_geographic_section(
            data,
            ctx.base,
            workspace_data_dir=ctx.workspace_data_dir,
            allow_dem_bootstrap=ctx.allow_dem_bootstrap,
        ),
        default={},
        required=True,
    ),
    "domain": Section(_standard(DomainConfig), default={}),
    "data": Section(
        lambda data, ctx: DataManagersConfig.from_toml_section(
            data, base_dir=ctx.base, workspace_data_dir=ctx.workspace_data_dir
        ),
        default={},
    ),
    "flow": Section(
        lambda data, ctx: FlowConfig.from_toml_section(
            {} if data is None else data,
            base_dir=ctx.base,
            workspace_data_dir=ctx.workspace_data_dir,
        ),
        default={},
    ),
    "transport": Section(_standard(TransportConfig), default={}),
    "simulation": Section(_standard(SimulationConfig), default={}),
    "solver": Section(_standard(SolverConfig), default={}),
    "display": Section(_standard(DisplayConfig), default={}),
    "export": Section(lambda data, _ctx: load_export_requests(data), default=[]),
    "observation": Section(_standard(ObservationConfig), default={}),
    "overview": Section(_optional(OverviewConfig), default=None),
    "mesh": Section(lambda data, ctx: _load_optional_mesh_section(data, ctx.base), default=None),
    "calibration": Section(
        lambda data, ctx: _load_optional_calibration_section(data, ctx.base, sealed=ctx.sealed),
        default=None,
    ),
    "spinup": Section(_optional(SpinupConfig), default=None),
    "site": Section(_as_written("site"), default=None),
    "sites": Section(_as_written("sites"), default=None),
    "metrics": Section(_as_written("metrics"), default=None),
    "publication": Section(_as_written("publication"), default=None),
    "workflow": Section(
        _as_written("workflow"),
        default=ABSENT,
        mapping_refusal="TOML section [workflow] must be a mapping with key 'mode'",
    ),
}
"""The root sections in the order the loader validates them, the workspace first.

``[workspace]`` comes first because every other loader reads the shared data
folder it names. A new section is one row here and one field of the root.
"""


def validate_sections(
    root: type[BaseModel],
    resolved: Resolved,
    *,
    base: Path,
    sealed: bool = False,
    source_path: Path | None = None,
) -> tuple[dict[str, Any], list[Fault]]:
    """Validate each section of ``SECTIONS`` on its own and return them with every fault.

    A fault of one section does not stop the next. Each fault gives its
    diagnostics, a required key left out folded into ``to_fill``, and the
    exception the loader raises for it alone. A section left out takes the
    default of its row; ``[workflow]`` left out is not handed to the root.
    """
    raw = resolved.raw
    ctx = SectionContext(root, base, None, resolved.allow_dem_bootstrap, sealed)
    sections: dict[str, Any] = {}
    faults: list[Fault] = []
    for name, section in SECTIONS.items():
        if name in resolved.skipped:
            continue
        written = name == "workspace" or name in raw
        data = resolved.workspace if name == "workspace" else raw.get(name, section.default)
        if not written and section.default is ABSENT:
            continue
        if section.mapping_refusal is not None and not isinstance(data, Mapping):
            faults.append(
                _section_fault(
                    name,
                    section.mapping_refusal,
                    error_type="dict_type",
                    root=root,
                    source_path=source_path,
                )
            )
            continue
        try:
            sections[name] = section.loader(data, ctx)
        except ValidationError as exc:
            diagnostics = diagnostics_of(
                exc, root=root, loc_prefix=(name,), document=raw, source_path=source_path
            )
            error: Exception = validation_refusal(
                exc, loc_prefix=(name,), source_path=source_path, document=raw
            )
        except ValueError as exc:
            fault = _section_fault(
                name, str(exc), error_type="value_error", root=root, source_path=source_path
            )
            diagnostics, error = list(fault.diagnostics), fault.error
        except HydroModPyError as exc:
            fault = _typed_fault(name, exc, root)
            diagnostics, error = list(fault.diagnostics), exc
        else:
            if name == "workspace":
                ctx = replace(ctx, workspace_data_dir=getattr(sections[name], "data_dir", None))
            continue
        if written or not section.required:
            holes = list(missing_keys(root.model_fields[name].annotation, data, (name,)))
        else:
            holes = [(name,)]
        faults.append(Fault(tuple(_fold_into_to_fill(diagnostics, holes, root)), error))
    return sections, faults


# ---------------------------------------------------------------------------
# The built document and the rules that read several sections
# ---------------------------------------------------------------------------


def faults_of_rules(
    outcomes: Sequence[RuleOutcome],
    *,
    root: type[BaseModel],
    document: Any,
    source_path: Path | None = None,
) -> list[Fault]:
    """Return the fault of each rule that refused the document.

    A rule that raises a ``ValueError`` was refused through the validator of
    the root, as a Pydantic ``value_error`` of the whole document: the error is
    built the same way, so its message and its record are the ones a refusal
    always had. A typed error of a rule is kept as it is.
    """
    faults: list[Fault] = []
    for outcome in outcomes:
        exc = outcome.error
        if exc is None:
            continue
        detail = getattr(exc, "message", "") or str(exc)
        diagnostic = Diagnostic(
            path="",
            code=outcome.rule.code,
            severity="error",
            detail=detail,
            keys=(),
            error_type="value_error" if isinstance(exc, ValueError) else "",
        )
        if isinstance(exc, HydroModPyError):
            faults.append(Fault((diagnostic,), exc))
            continue
        wrapped = ValidationError.from_exception_data(
            root.__name__,
            [{"type": "value_error", "loc": (), "input": document, "ctx": {"error": exc}}],
        )
        error = validation_refusal(wrapped, source_path=source_path)
        error.__cause__ = exc
        faults.append(Fault((diagnostic,), error))
    return faults


def build_document(
    root: type[BaseModel],
    sections: Mapping[str, Any],
    resolved: Resolved,
    *,
    context: str,
    sealed: bool = False,
    source_path: Path | None = None,
) -> tuple[BaseModel | None, list[Fault], list[str]]:
    """Build the root from validated sections, then run the rules that read several of them.

    The root validates with ``cross_rules = "caller"`` in its context, so its
    validator leaves the rows of ``CROSS_RULES`` to this function, which runs
    every one of them and keeps every refusal. Returns the built root, or None
    when it is refused, the faults, and the warnings the rules gave.
    """
    try:
        cfg = root.model_validate(
            dict(sections),
            context={
                "allow_dem_bootstrap": resolved.allow_dem_bootstrap,
                "validation_context": context,
                "cross_rules": "caller",
            },
        )
    except ValidationError as exc:
        diagnostics = diagnostics_of(exc, root=root, document=resolved.raw, source_path=source_path)
        error = validation_refusal(exc, source_path=source_path, document=resolved.raw)
        return None, [Fault(tuple(diagnostics), error)], []
    except HydroModPyError as exc:
        return None, [_typed_fault("", exc, root)], []
    outcomes = run_cross_rules(cfg, sealed=sealed)
    said = [text for outcome in outcomes for text in outcome.warnings]
    return (
        cfg,
        faults_of_rules(outcomes, root=root, document=dict(sections), source_path=source_path),
        said,
    )
