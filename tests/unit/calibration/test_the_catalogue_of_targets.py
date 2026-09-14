"""What a project can calibrate has to be answerable without reading the code.

A parameter is declared by a dotted path into the configuration, and until now
finding a valid one meant knowing the Pydantic tree by heart. The question a
hydrogeologist actually asks is the other way round: what does THIS model expose
that I could search over, what is it worth now, and in what unit.

The catalogue answers from the resolved configuration, so it lists the
boundaries this project declares and the parameters it actually carries, not a
hand-written inventory that drifts.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.targets import calibration_targets, targets_by_path
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _config(tmp_path, **flow: object):
    from hydromodpy.config import HydroModPyConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(**flow),
    )


@pytest.fixture
def cfg(tmp_path):
    return _config(
        tmp_path,
        param_list=["K", "Sy"],
        param={
            "K": {"field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-5}},
            "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "unit": "-", "value": 0.1}},
        },
    )


class TestWhatItLists:
    def test_it_lists_every_declared_flow_parameter(self, cfg) -> None:
        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert "flow.param.Sy.field.value" in found

    def test_a_target_carries_what_the_value_is_now(self, cfg) -> None:
        target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

        assert target.current == pytest.approx(1e-5)
        assert target.instance == "K"

    def test_a_target_carries_the_unit_its_neighbour_declares(self, cfg) -> None:
        target = targets_by_path(calibration_targets(cfg))["flow.param.K.field.value"]

        assert target.units == "m/s"

    def test_a_target_the_registry_knows_carries_its_physical_range(self, cfg) -> None:
        found = targets_by_path(calibration_targets(cfg))

        assert found["flow.param.K.field.value"].physical_bounds == (1e-14, 1e2)
        assert found["flow.param.Sy.field.value"].physical_bounds == (1e-4, 0.5)

    def test_a_target_the_registry_does_not_know_says_so_rather_than_guessing(
        self, tmp_path
    ) -> None:
        cfg = _config(
            tmp_path,
            param_list=["weird"],
            param={
                "weird": {
                    "field": {"id": "weird", "kind": "homogeneous", "unit": "-", "value": 3.0}
                }
            },
        )

        target = targets_by_path(calibration_targets(cfg))["flow.param.weird.field.value"]

        assert target.physical_bounds is None

    def test_a_project_declaring_nothing_lists_nothing_rather_than_failing(self, tmp_path) -> None:
        assert calibration_targets(_config(tmp_path)) is not None


class TestWhatItLeavesOut:
    def test_a_flag_is_not_a_target(self, cfg) -> None:
        """A boolean is a switch, not a value to search between two bounds."""
        paths = targets_by_path(calibration_targets(cfg))

        assert not any(isinstance(target.current, bool) for target in paths.values())

    def test_the_mesh_is_not_offered(self, cfg) -> None:
        paths = targets_by_path(calibration_targets(cfg))

        assert not any(path.startswith("mesh") for path in paths)

    def test_every_listed_path_is_one_a_parameter_may_declare(self, cfg) -> None:
        """The catalogue would be a trap if it named a path the space refuses."""
        from hydromodpy.calibration.optim.parameters import ParameterSpace

        for target in calibration_targets(cfg):
            space = ParameterSpace.from_toml_mapping(
                {"p": {"bounds": [1.0, 2.0], "path": target.path}}
            )
            assert space is not None


class TestTheOrdering:
    def test_targets_come_back_in_path_order(self, cfg) -> None:
        paths = [target.path for target in calibration_targets(cfg)]

        assert paths == sorted(paths)
