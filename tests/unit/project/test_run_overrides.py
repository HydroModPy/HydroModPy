"""An override of a run is a change of its configuration, by one vocabulary.

``simulate(K=...)``, ``Project.rerun(set=...)``, ``hmp catalog rerun --set`` and the
lineage of the seal all speak dotted paths, and the configuration takes them in one
place, validated. Before this, the keywords patched a ``Flow`` built on the side,
and a replay of the run went back to the value of the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.project.run_overrides import override_changes
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

K_PATH = "flow.param.K.field.value"


def _config(tmp_path: Path, *, domain: dict | None = None, unit: str = "m/s") -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        domain=domain or {"depth_model": {"kind": "constant_thickness", "thickness": 50.0}},
        flow={
            "param_list": ["K", "Sy"],
            "param": {
                "K": {"field": {"id": "K", "kind": "homogeneous", "value": 1e-4, "unit": unit}},
                "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "value": 0.1}},
            },
        },
    )


@pytest.mark.parametrize(
    ("keyword", "value", "path"),
    [
        ("K", 2e-5, K_PATH),
        ("Sy", 0.2, "flow.param.Sy.field.value"),
        ("thickness", 70.0, "domain.depth_model.thickness"),
        ("first_clim", "first", "flow.sinks_sources.recharge.first_clim"),
    ],
)
def test_a_keyword_is_shorthand_for_its_path(
    tmp_path: Path, keyword: str, value: object, path: str
) -> None:
    assert override_changes(_config(tmp_path), {keyword: value}) == {path: value}


def test_no_keyword_is_no_change_and_no_walk(tmp_path: Path) -> None:
    assert override_changes(object(), {}) == {}


def test_an_unknown_keyword_names_what_this_project_offers(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"Unknown parameter 'porosity'.*K, Sy, first_clim"):
        override_changes(_config(tmp_path), {"porosity": 0.3})


def test_a_thickness_on_a_kind_that_has_none_says_so(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path, domain={"depth_model": {"kind": "flat_substratum", "substratum_elevation": 10.0}}
    )
    with pytest.raises(ConfigError, match="'flat_substratum' has no thickness"):
        override_changes(cfg, {"thickness": 30.0})


def test_a_change_reaches_the_copy_and_leaves_the_declared_configuration_alone(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path)
    changed = cfg.with_changes({"domain.depth_model.thickness": 99.0, K_PATH: 3e-5})

    assert changed.domain.depth_model.thickness == 99.0
    assert changed.flow.param["K"].field.value == pytest.approx(3e-5)
    assert changed.flow.param["K"].field.unit == "m/s"
    assert cfg.domain.depth_model.thickness == 50.0
    assert cfg.flow.param["K"].field.value == pytest.approx(1e-4)


def test_a_change_shares_every_section_it_does_not_touch(tmp_path: Path) -> None:
    """A built domain or flow compares its section by identity, so identity is the point."""
    cfg = _config(tmp_path)

    only_flow = cfg.with_changes({K_PATH: 3e-5})
    assert only_flow.domain is cfg.domain
    assert only_flow.simulation is cfg.simulation
    assert only_flow.flow is not cfg.flow

    only_domain = cfg.with_changes({"domain.depth_model.thickness": 99.0})
    assert only_domain.flow is cfg.flow
    assert only_domain.domain is not cfg.domain


def test_a_number_is_read_in_the_unit_the_file_declares(tmp_path: Path) -> None:
    changed = _config(tmp_path, unit="m/day").with_changes({K_PATH: 2.0})
    assert changed.flow.param["K"].field.unit == "m/day"
    assert changed.flow.param["K"].field.value == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({K_PATH: -1.0}, "K"),
        ({"flow.param.K.field.nonsense": 1}, "nonsense"),
        ({"nosection.key": 1}, "nosection"),
    ],
)
def test_a_change_is_validated_as_a_whole_document(
    tmp_path: Path, changes: dict, message: str
) -> None:
    with pytest.raises(ConfigValidationError, match=message):
        _config(tmp_path).with_changes(changes)


def test_a_snapshot_takes_the_same_paths(tmp_path: Path) -> None:
    snapshot = {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        "workspace": {"project_root": str(tmp_path)},
    }
    cfg = HydroModPyConfig.from_snapshot(snapshot, changes={"solver.drain_bed_thickness_m": 2.0})

    assert cfg.solver.drain_bed_thickness_m == pytest.approx(2.0)
    assert "solver" not in snapshot, "the snapshot of the caller is not touched"
