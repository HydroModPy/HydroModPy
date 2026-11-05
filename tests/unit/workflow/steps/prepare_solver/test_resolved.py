"""The resolved config a run seals."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.results.storage.contract import RUN_RESOLVED_CONFIG_FILENAME
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.terrain import registry as terrain_registry
from hydromodpy.workflow.steps.prepare_solver.resolved import (
    BUILD_TABLE,
    build_drift,
    config_drift,
    resolved_at_build,
    resolved_config_document,
)

# --- test_a_run_seals_its_resolved_config ---
# ``config.resolved.toml``: every key with its value, and what a replay compares.
#
# It is compared and never read back as a configuration. A replay computes the same
# document from the configuration it would run, so a key differs only when a default
# moved, the file changed, or a rule that derives a value changed.


def _config(tmp_path: Path, **sections) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        **sections,
    )


def _resolved(cfg: HydroModPyConfig, tmp_path: Path, **kwargs) -> dict:
    return tomllib.loads(resolved_config_document(cfg, tmp_path, **kwargs))


def _sealed(run_dir: Path, cfg: HydroModPyConfig, project: Path, **kwargs) -> Path:
    run_dir.mkdir(parents=True)
    (run_dir / RUN_RESOLVED_CONFIG_FILENAME).write_text(
        resolved_config_document(cfg, project, **kwargs), encoding="utf-8"
    )
    return run_dir


def test_every_default_is_written_and_no_machine_key(tmp_path: Path) -> None:
    resolved = _resolved(_config(tmp_path), tmp_path)

    assert resolved["solver"]["drain_bed_thickness_m"] == pytest.approx(1.0)
    assert "project_root" not in resolved.get("workspace", {})
    assert str(tmp_path) not in resolved_config_document(_config(tmp_path), tmp_path)


@pytest.mark.parametrize(
    ("sections", "path", "value"),
    [
        ({}, ("geographic", "terrain_engine"), terrain_registry.DEFAULT_ENGINE_ID),
        (
            {"mesh": {"lake_refinement": {"cell_size": 40.0}}},
            ("mesh", "lake_refinement", "shoreline_band"),
            80.0,
        ),
        (
            {"mesh": {"lake_refinement": {"cell_size": 40.0, "shoreline_band": 50.0}}},
            ("mesh", "lake_refinement", "shoreline_band"),
            50.0,
        ),
        (
            {"mesh": {"lake_refinement": {"dam_buffer": 100.0}}},
            ("mesh", "lake_refinement", "hfb_buffer"),
            200.0,
        ),
        ({"site": {"name": "s", "gauge": "G1"}}, ("metrics", "station"), "G1"),
        ({"metrics": {"station": "G2"}}, ("metrics", "station"), "G2"),
    ],
)
def test_a_value_a_rule_derives_is_spelled_out(
    tmp_path: Path, sections: dict, path: tuple[str, ...], value: object
) -> None:
    held: object = _resolved(_config(tmp_path, **sections), tmp_path)
    for key in path:
        held = held[key]
    assert held == value


def test_an_unchanged_configuration_has_no_drift(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    run_dir = _sealed(tmp_path / "runs" / "x", cfg, tmp_path)
    assert config_drift(cfg, run_dir, project_root=tmp_path) == ()


def test_a_run_that_sealed_no_file_says_so(tmp_path: Path) -> None:
    assert config_drift(_config(tmp_path), tmp_path, project_root=tmp_path) is None


def test_a_change_is_named_with_both_values(tmp_path: Path) -> None:
    run_dir = _sealed(
        tmp_path / "runs" / "x", _config(tmp_path, solver={"drain_bed_thickness_m": 1.0}), tmp_path
    )
    changed = _config(tmp_path, solver={"drain_bed_thickness_m": 2.0})

    drift = config_drift(changed, run_dir, project_root=tmp_path)

    assert [item.line() for item in drift] == [
        "solver.drain_bed_thickness_m: sealed 1.0, now 2.0",
    ]
    assert drift[0].record() == {"sealed": 1.0, "effective": 2.0}


def test_a_key_on_one_side_only_says_which(tmp_path: Path) -> None:
    run_dir = _sealed(tmp_path / "runs" / "x", _config(tmp_path), tmp_path)
    document = tomllib.loads((run_dir / RUN_RESOLVED_CONFIG_FILENAME).read_text())
    document["solver"]["a_key_of_an_older_version"] = 3
    (run_dir / RUN_RESOLVED_CONFIG_FILENAME).write_text(dumps(document), encoding="utf-8")

    drift = config_drift(_config(tmp_path), run_dir, project_root=tmp_path)

    assert [item.line() for item in drift] == [
        "solver.a_key_of_an_older_version: sealed 3, now (not written)",
    ]
    assert drift[0].record() == {"sealed": 3}


def test_what_the_caller_asked_to_change_is_no_drift(tmp_path: Path) -> None:
    run_dir = _sealed(tmp_path / "runs" / "x", _config(tmp_path), tmp_path)
    asked = _config(tmp_path, solver={"drain_bed_thickness_m": 2.0})

    assert config_drift(asked, run_dir, project_root=tmp_path, intended=["solver"]) == (), (
        "a path covers what lies below it"
    )
    assert (
        config_drift(
            asked, run_dir, project_root=tmp_path, intended=["solver.drain_bed_thickness_m"]
        )
        == ()
    )
    assert config_drift(asked, run_dir, project_root=tmp_path, intended=["solver.other"]) != ()


def test_the_name_of_the_replay_is_no_drift(tmp_path: Path) -> None:
    run_dir = _sealed(
        tmp_path / "runs" / "x", _config(tmp_path, simulation={"name": "first"}), tmp_path
    )
    renamed = _config(tmp_path, simulation={"name": "second"})
    assert config_drift(renamed, run_dir, project_root=tmp_path) == ()


def test_where_an_input_file_sits_is_no_drift_and_its_digest_answers_for_it(tmp_path: Path) -> None:
    def with_dem(path: str) -> HydroModPyConfig:
        return HydroModPyConfig(
            workflow={"mode": "simulation"},
            workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
            site={"name": "s"},
            geographic={"catchment": {"kind": "dem", "dem_init_path": path}},
        )

    run_dir = _sealed(tmp_path / "runs" / "x", with_dem("dem/first.tif"), tmp_path)
    assert config_drift(with_dem("inputs/abc.tif"), run_dir, project_root=tmp_path) == ()


def _build_ctx(cfg: HydroModPyConfig, *, etp=None, sizes=None, hydrometry=None) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=cfg,
        loaded_data=SimpleNamespace(hydrometry=hydrometry),
        setup=SimpleNamespace(
            flow=SimpleNamespace(sinks_sources={"etp": etp} if etp is not None else {}),
            mesh_summary={"sizes": sizes} if sizes else {},
        ),
    )


def test_the_etp_the_data_step_injected_is_recorded_with_its_surface(tmp_path: Path) -> None:
    """Without a table ``[flow.sinks_sources.etp]``, nothing in the file says so."""
    decided = resolved_at_build(
        _build_ctx(_config(tmp_path), etp=FlowEtpConfig(surface_offset=2.0, extinction_depth=1.5))
    )
    etp = decided["flow"]["sinks_sources"]["etp"]
    assert etp["injected"] is True
    assert etp["surface_offset_m"] == pytest.approx(2.0)
    assert etp["surface_reference"] == "topographic surface"
    assert etp["extinction_depth_m"] == pytest.approx(1.5)


def test_the_etp_a_soil_leaves_is_read_against_the_drain(tmp_path: Path) -> None:
    etp = FlowEtpConfig(surface_offset=0.0)
    etp._from_soil_reservoir = True
    decided = resolved_at_build(_build_ctx(_config(tmp_path), etp=etp))
    held = decided["flow"]["sinks_sources"]["etp"]
    assert held["surface_offset_m"] == pytest.approx(0.0)
    assert held["surface_reference"] == "drain elevation"


def test_the_sizes_the_mesh_took_from_the_pixel_are_recorded(tmp_path: Path) -> None:
    decided = resolved_at_build(
        _build_ctx(_config(tmp_path), sizes={"pixel": 25.0, "cell_size": 25.0})
    )
    assert decided["mesh"] == {"pixel": 25.0, "cell_size": 25.0}


def test_the_gauge_a_run_deduced_is_recorded_when_the_file_names_none(tmp_path: Path) -> None:
    one_station = SimpleNamespace(points=[SimpleNamespace(station_id="ST1", id="ST1")])
    decided = resolved_at_build(_build_ctx(_config(tmp_path), hydrometry=one_station))
    assert decided["metrics"]["station"] == "ST1"

    named = _config(tmp_path, site={"name": "s", "gauge": "G1"})
    assert "metrics" not in resolved_at_build(_build_ctx(named, hydrometry=one_station))


def test_what_the_build_decided_is_kept_apart_and_compared_after_the_build(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    source = _sealed(tmp_path / "runs" / "x", cfg, tmp_path, build={"mesh": {"pixel": 25.0}})
    replay = _sealed(tmp_path / "runs" / "y", cfg, tmp_path, build={"mesh": {"pixel": 50.0}})

    assert _resolved(cfg, tmp_path, build={"mesh": {"pixel": 25.0}})[BUILD_TABLE]
    assert config_drift(cfg, source, project_root=tmp_path) == (), "not known before the build"
    assert [item.line() for item in build_drift(source, replay)] == [
        "mesh.pixel: sealed 25.0, now 50.0",
    ]
