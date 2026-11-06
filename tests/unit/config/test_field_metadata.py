"""Invariants for ``Field.json_schema_extra`` metadata across the codebase."""

from __future__ import annotations

import importlib
import json
import pkgutil
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.field_metadata import (
    field_metadata,
    is_valid_field_metadata,
    unknown_metadata_keys,
)
from hydromodpy.physics.flow.runtime_config import FlowRuntimeConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.lake import FlowLakeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.simulation.planning.config import TransportProcessConfig
from hydromodpy.solver.base.solver_config import CustomBackend, SolverConfig
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from tools.docs import field_registry

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_SCHEMA = ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"

#: What decision D10 of the 2.0.0 campaign calls experimental, field by field.
MARKED: dict[type[BaseModel], tuple[str, ...]] = {
    HydroModPyConfig: ("calibration",),
    FlowRuntimeConfig: (
        "backend",
        "max_iterations",
        "tol_residual_inf",
        "tol_state_update_inf",
        "vi_substeps_per_period",
        "vi_substep_on_failure",
        "vi_max_adaptive_substeps",
        "ts_vi_steps_per_period",
        "ts_vi_adapt",
        "ts_vi_dt_min_fraction",
        "ts_vi_dt_max_fraction",
        "ts_vi_type",
        "ts_vi_snes_type",
        "partition_release_depth_m",
    ),
    TransportConfig: ("modflow6prt", "modpath"),
    FlowSinksSourcesConfig: ("flow_barriers",),
    FlowLakeConfig: ("cutoff_wall",),
    SoilReservoirConfig: (
        "curve_number",
        "runoff_time",
        "runoff_lag",
        "transit_time",
        "bypass_fraction",
        "impervious_fraction",
        "spinup",
        "alpha",
        "kc",
    ),
    GeographicConfig: ("domain_extent",),
    CustomBackend: ("name",),
}
MARKED_FIELDS = [(model, field) for model, fields in MARKED.items() for field in fields]

#: A value of a selector, on a key that stays stable for its other values.
MARKED_VALUES: dict[tuple[type[BaseModel], str], tuple[str, ...]] = {
    (FlowRuntimeConfig, "surface_interaction_model"): (
        "complementarity",
        "vi_obstacle",
        "ts_vi_obstacle",
    ),
    (TransportProcessConfig, "solvers"): ("modpath", "modflow6_prt"),
}

#: What D8 and D10 keep stable. A mark there would be noise and protect from nothing.
STABLE_FIELDS: tuple[tuple[type[BaseModel], str], ...] = (
    (SolverConfig, "drain_bed_thickness_m"),
    (SolverConfig, "drain_band_depth_m"),
    (HydroModPyConfig, "mesh"),
    (MeshConfig, "families"),
    (MeshConfig, "voronoi"),
    (Modflow6Config, "runtime"),
    (SoilReservoirConfig, "ru"),
    (TransportConfig, "mt3dms"),
    (TransportConfig, "modflow6gwt"),
)


def _extra(model: type[BaseModel], field: str) -> dict:
    return model.model_fields[field].json_schema_extra or {}


def _schema_properties(schema: dict, model: type[BaseModel]) -> dict:
    node = schema if model is HydroModPyConfig else schema["$defs"][model.__name__]
    return node["properties"]


@pytest.fixture(scope="module")
def published_schema() -> dict:
    return json.loads(PUBLISHED_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return field_registry.build()


@pytest.fixture(scope="module")
def chips():
    """The badges of a key line, from the Sphinx extension that draws them."""
    ext = ROOT / "docs" / "source" / "_ext"
    sys.path.insert(0, str(ext))
    yield importlib.import_module("hmp_tview").chips
    sys.path.remove(str(ext))


@pytest.mark.parametrize(("model", "field"), MARKED_FIELDS)
def test_a_listed_field_carries_the_mark(model: type[BaseModel], field: str) -> None:
    assert _extra(model, field).get("stability") == "experimental"


@pytest.mark.parametrize(("model", "field"), MARKED_FIELDS)
def test_the_published_schema_carries_the_mark(
    published_schema: dict, model: type[BaseModel], field: str
) -> None:
    assert _schema_properties(published_schema, model)[field]["stability"] == "experimental"


@pytest.mark.parametrize(("selector", "values"), MARKED_VALUES.items())
def test_a_selector_marks_its_values_and_not_itself(
    published_schema: dict, selector: tuple[type[BaseModel], str], values: tuple[str, ...]
) -> None:
    model, field = selector
    assert "stability" not in _extra(model, field)
    assert set(_extra(model, field)["experimental_values"]) == set(values)
    assert set(_schema_properties(published_schema, model)[field]["experimental_values"]) == set(
        values
    )


@pytest.mark.parametrize(("model", "field"), STABLE_FIELDS)
def test_what_stays_stable_has_no_mark(model: type[BaseModel], field: str) -> None:
    assert "stability" not in _extra(model, field)


def test_the_calibration_section_says_it_is_experimental_too() -> None:
    assert "experimental" in (CalibrationConfig.__doc__ or "")


def test_the_drain_bed_thickness_says_its_value_has_no_measured_source() -> None:
    description = SolverConfig.model_fields["drain_bed_thickness_m"].description or ""
    assert "convention with no measured source" in description


@pytest.mark.parametrize(
    "path",
    [
        "calibration",
        "calibration.method",
        "transport.modflow6prt",
        "transport.modflow6prt.parameters",
        "transport.modpath.parameters.track_dir",
        "flow.sinks_sources.flow_barriers",
        "flow.sinks_sources.flow_barriers.<name>.hydchr",
        "flow.sinks_sources.lakes.<name>.cutoff_wall",
        "flow.sinks_sources.lakes.<name>.cutoff_wall.depths",
        "flow.sinks_sources.recharge.soil.alpha",
        "flow.runtime.vi_substeps_per_period",
        "geographic.domain_extent",
        "solver.backend.name",
    ],
)
def test_the_docs_show_the_mark_on_a_key_and_below_a_marked_section(
    registry: dict, chips, path: str
) -> None:
    node = registry[path]
    assert node["stability"] == "experimental"
    assert '<span class="tc tc-exp">experimental</span>' in chips(node, in_variant=True)


@pytest.mark.parametrize(
    "path",
    [
        "flow.first_period_steady",
        "flow.sinks_sources.recharge.soil.ru",
        "transport.mt3dms.parameters",
        "solver.backend",
    ],
)
def test_the_docs_show_no_mark_beside_a_marked_key(registry: dict, path: str) -> None:
    assert not registry[path].get("stability")


def test_the_docs_show_which_values_of_a_selector_are_marked(registry: dict, chips) -> None:
    node = registry["flow.runtime.surface_interaction_model"]
    assert not node["stability"]
    assert any(
        "experimental if" in chip and "vi_obstacle" in chip for chip in chips(node, in_variant=True)
    )
    solvers = registry["simulation.process.solvers"]
    assert any("modflow6_prt" in chip for chip in chips(solvers, in_variant=True))


def test_field_metadata_helper_accepts_canonical_keys() -> None:
    payload = field_metadata(
        widget_type="slider",
        unit="m/s",
        display_min=0.0,
        display_max=1.0,
        toml_exclude=False,
        group="advanced",
        stability="experimental",
    )
    assert is_valid_field_metadata(payload)


def test_field_metadata_helper_rejects_typos() -> None:
    with pytest.raises(ValueError, match="Unknown field_metadata keys"):
        field_metadata(widgettype="input")


def _iter_basemodel_classes():
    importlib.import_module("hydromodpy._bootstrap").bootstrap()
    package = importlib.import_module("hydromodpy")
    seen: set[type[BaseModel]] = set()
    for module_info in pkgutil.walk_packages(package.__path__, prefix="hydromodpy."):
        try:
            module = importlib.import_module(module_info.name)
        except BaseException:
            continue
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseModel)
                and attr is not BaseModel
                and attr not in seen
            ):
                seen.add(attr)
                yield attr


def test_no_unknown_keys_in_json_schema_extra_across_codebase() -> None:
    """All ``Field.json_schema_extra`` payloads use only canonical keys."""
    offenders: dict[str, set[str]] = {}
    for cls in _iter_basemodel_classes():
        for field_name, info in cls.model_fields.items():
            extra = info.json_schema_extra
            if not isinstance(extra, dict):
                continue
            unknown = unknown_metadata_keys(extra)
            if unknown:
                offenders[f"{cls.__module__}.{cls.__name__}.{field_name}"] = unknown

    assert not offenders, "Unknown json_schema_extra keys detected: " + ", ".join(
        f"{path}={sorted(keys)}" for path, keys in offenders.items()
    )


def test_a_description_that_says_experimental_carries_the_mark() -> None:
    """The word in a description ages. The mark is what the docs and the run read."""
    offenders = [
        f"{cls.__module__}.{cls.__name__}.{field_name}"
        for cls in _iter_basemodel_classes()
        for field_name, info in cls.model_fields.items()
        if "experimental" in (info.description or "").lower()
        and (info.json_schema_extra or {}).get("stability") != "experimental"
    ]

    assert not offenders, "Prose instead of the mark in: " + ", ".join(offenders)


def test_no_field_description_names_a_dead_results_folder() -> None:
    """``results_stable/`` was replaced by ``.hmp/scratch/_preprocessing/``.

    A field description is the only documentation many users read, so it must
    not send them to a directory the code stopped writing.
    """
    offenders = [
        f"{cls.__module__}.{cls.__name__}.{field_name}"
        for cls in _iter_basemodel_classes()
        for field_name, info in cls.model_fields.items()
        if "results_stable" in (info.description or "")
    ]

    assert not offenders, "Dead 'results_stable/' path in: " + ", ".join(offenders)


@pytest.mark.parametrize(
    ("model_path", "field", "old_paths"),
    [
        (
            "calibration.config:CalibrationConfig",
            "method_options",
            ["calibration.optimizer_kwargs"],
        ),
        (
            "calibration.config:CalibPhaseDecl",
            "method_options",
            ["calibration.phases.optimizer_kwargs"],
        ),
        (
            "calibration.config:MatchingHydrographicNetworkOptions",
            "steady_method_options",
            ["calibration.protocol.steady_engine_options"],
        ),
        (
            "calibration.config:MatchingHydrographicNetworkOptions",
            "transient_method_options",
            ["calibration.protocol.transient_engine_options"],
        ),
        ("calibration.config:CalibrationConfig", "window", ["calibration.scoring_window"]),
        ("calibration.config:CalibPhaseDecl", "window", ["calibration.phases.scoring_window"]),
        (
            "calibration.config:MatchingHydrographicNetworkOptions",
            "window",
            ["calibration.protocol.scoring_window"],
        ),
        ("config.hydromodpy_config:HydroModPyConfig", "export", ["export.geotiff"]),
    ],
)
def test_a_renamed_field_names_the_paths_it_replaces(
    model_path: str, field: str, old_paths: list[str]
) -> None:
    module_name, class_name = model_path.split(":")
    model = getattr(importlib.import_module(f"hydromodpy.{module_name}"), class_name)
    extra = model.model_fields[field].json_schema_extra

    assert set(old_paths) <= set(extra["renamed_from"])
