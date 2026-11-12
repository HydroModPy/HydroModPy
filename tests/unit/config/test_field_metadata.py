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
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.field_metadata import (
    field_metadata,
    unknown_metadata_keys,
)
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.solver.base.simulation_config import TransportProcessConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from tools.docs import field_registry

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_SCHEMA = ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"

#: What decision D10 of the 2.0.0 campaign calls experimental, field by field.
MARKED: dict[type[BaseModel], tuple[str, ...]] = {
    HydroModPyConfig: ("calibration",),
    BoussinesqOptions: (
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
}
MARKED_FIELDS = [(model, field) for model, fields in MARKED.items() for field in fields]

#: A value of a selector, on a key that stays stable for its other values.
MARKED_VALUES: dict[tuple[type[BaseModel], str], tuple[str, ...]] = {
    (BoussinesqOptions, "surface_interaction_model"): (
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
def test_listed_field_is_marked(model: type[BaseModel], field: str) -> None:
    assert _extra(model, field).get("stability") == "experimental"


@pytest.mark.parametrize(("model", "field"), MARKED_FIELDS)
def test_schema_carries_mark(published_schema: dict, model: type[BaseModel], field: str) -> None:
    assert _schema_properties(published_schema, model)[field]["stability"] == "experimental"


@pytest.mark.parametrize(("selector", "values"), MARKED_VALUES.items())
def test_selector_marks_values(
    published_schema: dict, selector: tuple[type[BaseModel], str], values: tuple[str, ...]
) -> None:
    model, field = selector
    assert "stability" not in _extra(model, field)
    assert set(_extra(model, field)["experimental_values"]) == set(values)
    assert set(_schema_properties(published_schema, model)[field]["experimental_values"]) == set(
        values
    )


@pytest.mark.parametrize(("model", "field"), STABLE_FIELDS)
def test_stable_fields_unmarked(model: type[BaseModel], field: str) -> None:
    assert "stability" not in _extra(model, field)


def test_calibration_doc_says_experimental() -> None:
    assert "experimental" in (CalibrationConfig.__doc__ or "")


def test_drain_bed_thickness_description() -> None:
    description = SolverConfig.model_fields["drain_bed_thickness_m"].description or ""
    assert "convention with no measured source" in description


@pytest.mark.parametrize(
    "path",
    [
        "flow.first_period_steady",
        "flow.sinks_sources.recharge.soil.ru",
        "transport.mt3dms",
        "solver.backend",
    ],
)
def test_docs_stable_keys_unmarked(registry: dict, path: str) -> None:
    assert not registry[path].get("stability")


def test_docs_chips_marked_values(registry: dict, chips) -> None:
    node = registry["solver.boussinesq.surface_interaction_model"]
    assert not node["stability"]
    assert any(
        "experimental if" in chip and "vi_obstacle" in chip for chip in chips(node, in_variant=True)
    )
    solvers = registry["simulation.process.solvers"]
    assert any("modflow6_prt" in chip for chip in chips(solvers, in_variant=True))


def test_metadata_rejects_typos() -> None:
    with pytest.raises(ValueError, match="Unknown field_metadata keys"):
        field_metadata(widgettype="input")


def _iter_basemodel_classes():
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


def test_no_unknown_extra_keys() -> None:
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


def test_experimental_text_has_mark() -> None:
    """The word in a description ages. The mark is what the docs and the run read."""
    offenders = [
        f"{cls.__module__}.{cls.__name__}.{field_name}"
        for cls in _iter_basemodel_classes()
        for field_name, info in cls.model_fields.items()
        if "experimental" in (info.description or "").lower()
        and (info.json_schema_extra or {}).get("stability") != "experimental"
    ]

    assert not offenders, "Prose instead of the mark in: " + ", ".join(offenders)


@pytest.mark.parametrize(
    ("model_path", "field", "old_paths"),
    [
        (
            "calibration.config:CalibrationConfig",
            "method_options",
            ["calibration.optimizer_kwargs"],
        ),
        (
            "calibration.config_phases:CalibPhaseDecl",
            "method_options",
            ["calibration.phases.optimizer_kwargs"],
        ),
        (
            "calibration.config_network:MatchingHydrographicNetworkOptions",
            "steady_method_options",
            ["calibration.protocol.steady_engine_options"],
        ),
        (
            "calibration.config_network:MatchingHydrographicNetworkOptions",
            "transient_method_options",
            ["calibration.protocol.transient_engine_options"],
        ),
        ("calibration.config:CalibrationConfig", "window", ["calibration.scoring_window"]),
        (
            "calibration.config_phases:CalibPhaseDecl",
            "window",
            ["calibration.phases.scoring_window"],
        ),
        (
            "calibration.config_network:MatchingHydrographicNetworkOptions",
            "window",
            ["calibration.protocol.scoring_window"],
        ),
        ("config.hydromodpy_config:HydroModPyConfig", "export", ["export.geotiff"]),
    ],
)
def test_renamed_field_paths(model_path: str, field: str, old_paths: list[str]) -> None:
    module_name, class_name = model_path.split(":")
    model = getattr(importlib.import_module(f"hydromodpy.{module_name}"), class_name)
    extra = model.model_fields[field].json_schema_extra

    assert set(old_paths) <= set(extra["renamed_from"])
