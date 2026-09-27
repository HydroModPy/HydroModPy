"""The aquifer geometry is a value a search may move, when it is one number.

Abherve et al. (2023) fix the thickness at 30 m and call it an input, and a
study of how the stream network depends on it has to vary it. A
``constant_thickness`` model holds the geometry in one thickness, and a
``flat_substratum`` model in one elevation: each is searchable, and the
catalogue names it the way a hydrogeologist would.

A raster depth model is a map of the site. A scalar written into it would shift
or scale the whole map, which is not what the raster answers, so it is refused
with the kind named, rather than by the generic "names nothing" a reader cannot
act on.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.parameter_resolution import (
    UnresolvedParameterName,
    resolve_parameter_targets,
    unresolved_parameter_names,
)
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
    RasterSubstratumDepthModel,
    RasterThicknessDepthModel,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig


class _Config:
    """The smallest thing the catalogue walks: a domain and no flow."""

    def __init__(self, depth_model: object) -> None:
        self.domain = DomainConfig(depth_model=depth_model)


def _calibration(**parameters: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": parameters})


class TestTheSchemaTakesWhatASearchWrites:
    def test_a_float_written_into_the_thickness_is_read_as_metres(self) -> None:
        cfg = _Config(ConstantThicknessDepthModel(thickness="30 m"))
        param = CalibParameter(
            name="thickness", lower=5.0, upper=300.0, path="domain.depth_model.thickness"
        )

        apply_parameter_to_config(cfg, param, 80.0)

        assert cfg.domain.depth_model.thickness == pytest.approx(80.0)

    def test_a_thickness_that_is_not_positive_is_refused_when_written(self) -> None:
        model = ConstantThicknessDepthModel(thickness="30 m")

        with pytest.raises(ValueError, match="greater than 0"):
            model.thickness = -1.0

    def test_a_substratum_elevation_may_be_written_below_sea_level(self) -> None:
        cfg = _Config(FlatSubstratumDepthModel(substratum_elevation="10 m"))
        param = CalibParameter(
            name="substratum_elevation",
            lower=-50.0,
            upper=50.0,
            path="domain.depth_model.substratum_elevation",
        )

        apply_parameter_to_config(cfg, param, -20.0)

        assert cfg.domain.depth_model.substratum_elevation == pytest.approx(-20.0)


class TestTheCatalogueNamesTheGeometry:
    def test_a_constant_thickness_is_listed_as_thickness(self) -> None:
        names = targets_by_name(
            calibration_targets(_Config(ConstantThicknessDepthModel(thickness="30 m")))
        )

        target = names["thickness"]
        assert target.path == "domain.depth_model.thickness"
        assert target.current == pytest.approx(30.0)
        assert target.units == "m"
        assert target.physical_bounds == (0.0, 10_000.0)

    def test_a_flat_substratum_is_listed_as_its_elevation(self) -> None:
        names = targets_by_name(
            calibration_targets(_Config(FlatSubstratumDepthModel(substratum_elevation="12 m")))
        )

        target = names["substratum_elevation"]
        assert target.path == "domain.depth_model.substratum_elevation"
        assert target.current == pytest.approx(12.0)
        # The registry knows an elevation, not a substratum_elevation.
        assert target.registry_id == "elevation"
        assert target.physical_bounds == (-500.0, 9000.0)

    def test_only_the_field_of_the_declared_kind_is_listed(self) -> None:
        names = targets_by_name(
            calibration_targets(_Config(FlatSubstratumDepthModel(substratum_elevation="12 m")))
        )

        assert "thickness" not in names

    @pytest.mark.parametrize("model", [RasterSubstratumDepthModel(), RasterThicknessDepthModel()])
    def test_a_raster_depth_model_lists_nothing(self, model: object) -> None:
        assert calibration_targets(_Config(model)) == []

    def test_every_geometry_target_is_one_a_parameter_may_declare(self) -> None:
        for model in (
            ConstantThicknessDepthModel(thickness="30 m"),
            FlatSubstratumDepthModel(substratum_elevation="12 m"),
        ):
            (target,) = calibration_targets(_Config(model))
            space = ParameterSpace.from_toml_mapping(
                {"p": {"bounds": [1.0, 2.0], "path": target.path}}
            )
            assert space.parameters[0].effective_path == target.path


class TestTheNameResolves:
    def test_thickness_resolves_and_is_searched_in_log_space(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        resolve_parameter_targets(
            calibration, _Config(ConstantThicknessDepthModel(thickness="30 m"))
        )

        decl = calibration.parameters["thickness"]
        assert decl.path == "domain.depth_model.thickness"
        assert decl.transform == "log"
        assert decl.prior == "log_uniform"
        assert decl.units == "m"

    def test_the_long_spelling_resolves_to_the_same_value(self) -> None:
        calibration = _calibration(**{"depth_model.thickness": {"bounds": [5.0, 300.0]}})

        resolve_parameter_targets(
            calibration, _Config(ConstantThicknessDepthModel(thickness="30 m"))
        )

        assert calibration.parameters["depth_model.thickness"].path == (
            "domain.depth_model.thickness"
        )

    def test_substratum_elevation_is_searched_in_linear_space(self) -> None:
        calibration = _calibration(substratum_elevation={"bounds": [-20.0, 15.0]})

        resolve_parameter_targets(
            calibration, _Config(FlatSubstratumDepthModel(substratum_elevation="0 m"))
        )

        decl = calibration.parameters["substratum_elevation"]
        assert decl.path == "domain.depth_model.substratum_elevation"
        assert decl.transform == "identity"
        assert decl.prior == "uniform"

    def test_a_thickness_bound_past_the_registry_is_refused(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 20_000.0]})

        with pytest.raises(ConfigError, match="20000"):
            resolve_parameter_targets(
                calibration, _Config(ConstantThicknessDepthModel(thickness="30 m"))
            )

    def test_an_elevation_bound_past_the_registry_is_refused(self) -> None:
        calibration = _calibration(substratum_elevation={"bounds": [-900.0, 10.0]})

        with pytest.raises(ConfigError, match="-900"):
            resolve_parameter_targets(
                calibration, _Config(FlatSubstratumDepthModel(substratum_elevation="0 m"))
            )


class TestWhatIsNotSearchableIsRefusedByItsKind:
    @pytest.mark.parametrize(
        ("model", "kind"),
        [
            (RasterThicknessDepthModel(), "raster_thickness"),
            (RasterSubstratumDepthModel(), "raster_substratum"),
        ],
    )
    def test_a_thickness_named_on_a_raster_names_the_raster(self, model, kind) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        with pytest.raises(UnresolvedParameterName, match=kind):
            resolve_parameter_targets(calibration, _Config(model))

    def test_a_thickness_named_on_a_flat_substratum_names_what_it_exposes(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        with pytest.raises(UnresolvedParameterName, match="'substratum_elevation'"):
            resolve_parameter_targets(
                calibration, _Config(FlatSubstratumDepthModel(substratum_elevation="0 m"))
            )

    def test_a_raster_offset_named_by_its_path_is_refused_even_when_lenient(self) -> None:
        """A path is otherwise the way out; into the depth model it is not."""
        calibration = _calibration(
            shift={"bounds": [-5.0, 5.0], "path": "domain.depth_model.offset"}
        )

        with pytest.raises(UnresolvedParameterName, match="raster_substratum"):
            resolve_parameter_targets(
                calibration, _Config(RasterSubstratumDepthModel()), strict=False
            )

    def test_a_thickness_path_on_a_flat_substratum_is_refused(self) -> None:
        calibration = _calibration(
            h={"bounds": [5.0, 300.0], "path": "domain.depth_model.thickness"}
        )

        with pytest.raises(UnresolvedParameterName, match="flat_substratum"):
            resolve_parameter_targets(
                calibration, _Config(FlatSubstratumDepthModel(substratum_elevation="0 m"))
            )

    def test_the_preflight_reads_the_same_reason(self) -> None:
        calibration = _calibration(thickness={"bounds": [5.0, 300.0]})

        refused = unresolved_parameter_names(calibration, _Config(RasterThicknessDepthModel()))

        assert "raster_thickness" in refused["thickness"]
        assert "exposes nothing" in refused["thickness"]


_TOML = textwrap.dedent(
    """
    [workspace]
    project_root = "PROJECT_ROOT"

    [workflow]
    mode = "simulation"

    [geographic]
    source_mode = "synthetic"

    [domain.depth_model]
    DEPTH_MODEL

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5
    """
)


def _project(tmp_path: Path, depth_model: str, calibration: str = "") -> Path:
    path = tmp_path / "project.toml"
    text = _TOML.replace("PROJECT_ROOT", str(tmp_path)).replace("DEPTH_MODEL", depth_model)
    path.write_text(text + calibration, encoding="utf-8")
    return path


class TestTheProjectFile:
    def test_a_thickness_named_in_the_file_is_resolved_at_load(self, tmp_path: Path) -> None:
        from hydromodpy.config import HydroModPyConfig

        path = _project(
            tmp_path,
            'kind = "constant_thickness"\nthickness = "30 m"',
            "\n[calibration.parameters.thickness]\nbounds = [5.0, 300.0]\n",
        )

        cfg = HydroModPyConfig.from_toml(path)

        decl = cfg.calibration.parameters["thickness"]
        assert decl.path == "domain.depth_model.thickness"
        assert decl.transform == "log"

    def test_a_thickness_path_on_a_flat_substratum_stops_the_load(self, tmp_path: Path) -> None:
        from hydromodpy.config import HydroModPyConfig

        path = _project(
            tmp_path,
            'kind = "flat_substratum"\nsubstratum_elevation = "5 m"',
            '\n[calibration.parameters.h]\nbounds = [5.0, 300.0]\npath = "domain.depth_model.thickness"\n',
        )

        with pytest.raises(UnresolvedParameterName, match="flat_substratum"):
            HydroModPyConfig.from_toml(path)

    def test_config_targets_lists_the_thickness(self, tmp_path: Path, capsys) -> None:
        import argparse

        from hydromodpy.cli.commands import config as config_cmd

        path = _project(tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"')

        config_cmd.run(argparse.Namespace(config_command="targets", file=str(path), json=False))

        out = capsys.readouterr().out
        line = next(row for row in out.splitlines() if row.startswith("thickness "))
        assert "domain.depth_model.thickness" in line
        assert "30" in line

    def test_config_targets_lists_the_substratum_elevation(self, tmp_path: Path, capsys) -> None:
        import argparse

        from hydromodpy.cli.commands import config as config_cmd

        path = _project(tmp_path, 'kind = "flat_substratum"\nsubstratum_elevation = "5 m"')

        config_cmd.run(argparse.Namespace(config_command="targets", file=str(path), json=False))

        out = capsys.readouterr().out
        assert "substratum_elevation" in out
        assert "domain.depth_model.thickness" not in out
