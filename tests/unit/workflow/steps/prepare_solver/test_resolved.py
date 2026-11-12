"""``config.resolved.toml``: the whole configuration a run used, and what a replay compares.

Every key is written with its value, so a key differs on replay only when a default moved, the file
changed, or a rule that derives a value changed. The frozen runs ``demo`` and ``calage`` were sealed
by a pre-release of 2.0 and must not drift where a table only moved. Lengths are in m, K in m/s.
"""

from __future__ import annotations

import shutil
import tomllib
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.catchment.terrain import registry as terrain_registry
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.results.storage.contract import RUN_RESOLVED_CONFIG_FILENAME
from hydromodpy.workflow.steps.prepare_solver.resolved import (
    BUILD_TABLE,
    build_drift,
    compare_with_sealed,
    config_drift,
    resolved_at_build,
    resolved_config_document,
)


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


def test_defaults_written_no_machine_key(tmp_path: Path) -> None:
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
def test_derived_values_spelled_out(
    tmp_path: Path, sections: dict, path: tuple[str, ...], value: object
) -> None:
    held: object = _resolved(_config(tmp_path, **sections), tmp_path)
    for key in path:
        held = held[key]
    assert held == value


def test_run_without_sealed_file(tmp_path: Path) -> None:
    assert config_drift(_config(tmp_path), tmp_path, project_root=tmp_path) is None


def test_change_names_both_values(tmp_path: Path) -> None:
    run_dir = _sealed(
        tmp_path / "runs" / "x", _config(tmp_path, solver={"drain_bed_thickness_m": 1.0}), tmp_path
    )
    changed = _config(tmp_path, solver={"drain_bed_thickness_m": 2.0})

    drift = config_drift(changed, run_dir, project_root=tmp_path)

    assert [item.line() for item in drift] == [
        "solver.drain_bed_thickness_m: sealed 1.0, now 2.0",
    ]
    assert drift[0].record() == {"sealed": 1.0, "effective": 2.0}


def test_key_on_one_side_only(tmp_path: Path) -> None:
    run_dir = _sealed(tmp_path / "runs" / "x", _config(tmp_path), tmp_path)
    document = tomllib.loads((run_dir / RUN_RESOLVED_CONFIG_FILENAME).read_text())
    document["solver"]["a_key_of_an_older_version"] = 3
    (run_dir / RUN_RESOLVED_CONFIG_FILENAME).write_text(dumps(document), encoding="utf-8")

    drift = config_drift(_config(tmp_path), run_dir, project_root=tmp_path)

    assert [item.line() for item in drift] == [
        "solver.a_key_of_an_older_version: sealed 3, now (not written)",
    ]
    assert drift[0].record() == {"sealed": 3}


def test_input_file_location_is_no_drift(tmp_path: Path) -> None:
    def with_dem(path: str) -> HydroModPyConfig:
        return HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "simulation"},
                "workspace": {"root": str(tmp_path)},
                "site": {"name": "s"},
                "geographic": {"catchment": {"kind": "dem"}},
                "data": {"types": ["dem"], "dem": {"sources": [{"source": "file", "path": path}]}},
            },
            base_dir=tmp_path,
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


def test_injected_etp_recorded_with_surface(tmp_path: Path) -> None:
    # Without a table ``[flow.sinks_sources.etp]``, nothing in the file says so.
    decided = resolved_at_build(
        _build_ctx(_config(tmp_path), etp=FlowEtpConfig(surface_offset=2.0, extinction_depth=1.5))
    )
    etp = decided["flow"]["sinks_sources"]["etp"]
    assert etp["injected"] is True
    assert etp["surface_offset_m"] == pytest.approx(2.0)
    assert etp["surface_reference"] == "topographic surface"
    assert etp["extinction_depth_m"] == pytest.approx(1.5)


def test_etp_read_from_built_model(tmp_path: Path) -> None:
    ctx = _build_ctx(_config(tmp_path))
    ctx.setup.model = SimpleNamespace(etp=FlowEtpConfig(surface_offset=3.0))

    held = resolved_at_build(ctx)["flow"]["sinks_sources"]["etp"]

    assert held["surface_offset_m"] == pytest.approx(3.0)


def test_soil_etp_read_against_drain(tmp_path: Path) -> None:
    etp = FlowEtpConfig(surface_offset=0.0)
    etp._from_soil_reservoir = True
    decided = resolved_at_build(_build_ctx(_config(tmp_path), etp=etp))
    held = decided["flow"]["sinks_sources"]["etp"]
    assert held["surface_offset_m"] == pytest.approx(0.0)
    assert held["surface_reference"] == "drain elevation"


def test_mesh_sizes_recorded(tmp_path: Path) -> None:
    decided = resolved_at_build(
        _build_ctx(_config(tmp_path), sizes={"pixel": 25.0, "cell_size": 25.0})
    )
    assert decided["mesh"] == {"pixel": 25.0, "cell_size": 25.0}


def test_deduced_gauge_recorded(tmp_path: Path) -> None:
    one_station = SimpleNamespace(points=[SimpleNamespace(station_id="ST1", id="ST1")])
    decided = resolved_at_build(_build_ctx(_config(tmp_path), hydrometry=one_station))
    assert decided["metrics"]["station"] == "ST1"

    named = _config(tmp_path, site={"name": "s", "gauge": "G1"})
    assert "metrics" not in resolved_at_build(_build_ctx(named, hydrometry=one_station))


def test_build_decisions_kept_apart(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    source = _sealed(tmp_path / "runs" / "x", cfg, tmp_path, build={"mesh": {"pixel": 25.0}})
    replay = _sealed(tmp_path / "runs" / "y", cfg, tmp_path, build={"mesh": {"pixel": 50.0}})

    assert _resolved(cfg, tmp_path, build={"mesh": {"pixel": 25.0}})[BUILD_TABLE]
    assert config_drift(cfg, source, project_root=tmp_path) == (), "not known before the build"
    assert [item.line() for item in build_drift(source, replay)] == [
        "mesh.pixel: sealed 25.0, now 50.0",
    ]


def _without(run_dir: Path, section: str, key: str) -> None:
    """Remove one key from the sealed file, as a version that did not know it wrote it."""
    resolved = run_dir / RUN_RESOLVED_CONFIG_FILENAME
    document = tomllib.loads(resolved.read_text(encoding="utf-8"))
    del document[section][key]
    resolved.write_text(dumps(document), encoding="utf-8")


NEW_KEYS = (
    (
        "a key the sealed file does not write, at its default",
        {},
        [],
        {"solver.drain_bed_thickness_m": 1.0},
    ),
    (
        "the same key written at its default",
        {"solver": {"drain_bed_thickness_m": 1.0}},
        [],
        {"solver.drain_bed_thickness_m": 1.0},
    ),
    (
        "the same key away from its default",
        {"solver": {"drain_bed_thickness_m": 2.0}},
        ["solver.drain_bed_thickness_m: sealed (not written), now 2.0"],
        {},
    ),
)


@pytest.mark.parametrize(
    ("case", "sections", "lines", "at_default"), NEW_KEYS, ids=[row[0] for row in NEW_KEYS]
)
def test_new_key_drifts_away_from_default(
    tmp_path: Path, case: str, sections: dict, lines: list[str], at_default: dict
) -> None:
    del case
    run_dir = _sealed(tmp_path / "runs" / "x", _config(tmp_path), tmp_path)
    _without(run_dir, "solver", "drain_bed_thickness_m")

    compared = compare_with_sealed(_config(tmp_path, **sections), run_dir, project_root=tmp_path)

    assert compared is not None
    assert [item.line() for item in compared.drift] == lines
    assert compared.new_at_default == at_default
    assert (
        config_drift(_config(tmp_path, **sections), run_dir, project_root=tmp_path)
        == compared.drift
    )


def test_comparison_without_sealed_file(tmp_path: Path) -> None:
    assert compare_with_sealed(_config(tmp_path), tmp_path, project_root=tmp_path) is None


FROZEN_DEMO = (
    Path(__file__).resolve().parents[5]
    / "tests/regression/frozen_runs/v2.0.0/current/projects/example/runs/demo"
)
FROZEN_CALAGE = (
    Path(__file__).resolve().parents[5]
    / "tests/regression/frozen_runs/v2.0.0/current/projects/example/runs/calage"
)

NEW_AT_DEFAULT = {
    "flow.sinks_sources.recharge.factor": 1.0,
    "simulation.results.keep_face_flows": False,
    "simulation.time.window": "all",
    "workspace.products_cap_mb": 5000,
}
"""What these copies do not write and a replay holds at its default, measured once.

The recharge factor came after these runs were sealed by a pre-release,
and its default reproduces the old computation. ``config_drift`` gave it as
the one drift before a key absent from the sealed file counted for none. The cap of the
product store came later and moves no number, and so did ``keep_face_flows``, whose default
writes no face flow. A file of a pre-release of 2.0 writes no window key, and
the default of ``simulation.time.window`` plays the run in one piece. The default of
``window_length`` is ``None``, which is not counted.
"""

COPIED = ("config.toml", "config.resolved.toml")


def copy_frozen_run(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run = tmp_path / "runs" / source.name
    run.mkdir(parents=True)
    for name in COPIED:
        shutil.copyfile(source / name, run / name)
    monkeypatch.chdir(tmp_path)
    return run


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return copy_frozen_run(FROZEN_DEMO, tmp_path, monkeypatch)


@pytest.fixture
def calage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return copy_frozen_run(FROZEN_CALAGE, tmp_path, monkeypatch)


def _config_of(run: Path) -> HydroModPyConfig:
    snapshot = tomllib.loads((run / "config.toml").read_text(encoding="utf-8"))
    return HydroModPyConfig.from_snapshot(snapshot)


def _drift_keys(run: Path) -> tuple[str, ...]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = _config_of(run)
        drift = config_drift(cfg, run, project_root=Path(cfg.workspace.project_root))
    assert drift is not None
    return tuple(item.key for item in drift)


def _new_at_default(run: Path) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = _config_of(run)
        compared = compare_with_sealed(cfg, run, project_root=Path(cfg.workspace.project_root))
    assert compared is not None
    return {key: value for key, value in compared.new_at_default.items() if key != "edition"}


def test_sealed_document_tables(demo: Path) -> None:
    sealed = tomllib.loads((demo / "config.resolved.toml").read_text(encoding="utf-8"))

    assert {"modflow6", "modflownwt"} <= set(sealed)
    assert "runtime" in sealed["flow"]
    assert sealed["solver"]["backend"] == {"kind": "modflow_nwt"}


@pytest.mark.parametrize("name", ["demo", "calage"])
def test_replay_of_2_0_run_does_not_drift(name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(name)

    assert _drift_keys(run) == ()
    assert _new_at_default(run) == NEW_AT_DEFAULT


def test_new_key_away_from_default_drifts(demo: Path) -> None:
    config = demo / "config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace(
            "[flow.sinks_sources.recharge]\n", "[flow.sinks_sources.recharge]\nfactor = 2.0\n"
        ),
        encoding="utf-8",
    )
    assert text != config.read_text(encoding="utf-8"), "the demo writes a recharge table"

    assert _drift_keys(demo) == ("flow.sinks_sources.recharge.factor",)
