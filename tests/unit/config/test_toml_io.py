"""Reading and writing the TOML of a project.

A file is read through its base files, with ``__merge`` tables paired by identity
and ``--set`` or ``HMP_SET_*`` overrides on top. A template is generated from the
config model, every skeleton commented so that it stays valid. Relative paths are
read from the project root.
"""

from __future__ import annotations

import json
import re
import textwrap
import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.core.toml_io.error_locator import locate_loc
from hydromodpy.core.toml_io.generator import generate_toml, generate_toml_from_instances
from hydromodpy.core.toml_io.loader import config_base_dir, load_toml_with_base_config
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.results.exporters.export_spec import load_export_requests

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures" / "projects" / "simulation_regression"

NEW_MF6 = "[solver.modflow6.process_specific]\nvka = {}\n"

MERGE_REFUSALS = [
    pytest.param(
        {"x": [{"a": 1}, {"a": 2}]},
        {"x__merge": [{"a": 3}, {"a": 4}]},
        "needs one of id, name or source",
        id="same length, no identity",
    ),
    pytest.param(
        {"x": [{"id": "a"}, {"id": "b"}]},
        {"x__merge": [{"label": "A"}]},
        "needs one of id, name or source",
        id="identity on one side",
    ),
    pytest.param(
        {"x": [{"id": "a"}]},
        {"x__merge": [{"id": "z"}]},
        "no inherited table has id = 'z'",
        id="unknown",
    ),
    pytest.param(
        {"x": [{"id": "a"}, {"id": "a"}]},
        {"x__merge": [{"id": "a"}]},
        "the inherited tables cannot be told apart",
        id="twice in the base",
    ),
    pytest.param(
        {"x": [{"id": "a"}]},
        {"x__merge": [{"id": "a"}, {"id": "a"}]},
        "the written tables cannot be told apart",
        id="twice in the overlay",
    ),
    pytest.param({}, {"x__merge": [{"a": 2}]}, "no inherited list", id="missing"),
    pytest.param({"x": [1]}, {"x__merge": [{"a": 2}]}, "inherited list of tables", id="values"),
    pytest.param({"x": [{"a": 1}]}, {"x__merge": [1]}, "requires a list of tables", id="items"),
    pytest.param(
        {"x": [{"a": 1}]},
        {"x": [{"a": 2}], "x__merge": [{"a": 3}]},
        "write only one of them",
        id="both",
    ),
]


def test_merge_pairs_one_table_without_an_identity() -> None:
    merged = merge_toml_payloads({"x": [{"a": 1, "b": 2}]}, {"x__merge": [{"b": 3}]})

    assert merged["x"] == [{"a": 1, "b": 3}]


def test_base_dir_of_a_sealed_file(tmp_path: Path) -> None:
    flat = tmp_path / "flat" / "runs" / "first"
    copy = tmp_path / "elsewhere" / "base"
    for folder in (flat, copy):
        folder.mkdir(parents=True)
        (folder / "config.toml").write_text("", encoding="utf-8")
        (folder / "manifest.json").write_text("{}", encoding="utf-8")

    # A sealed file writes its paths from the project root, wherever the run sits.
    assert config_base_dir(flat / "config.toml") == (tmp_path / "flat").resolve()
    # A copy outside its project reads from its own folder. A caller names the
    # project by argument (-w, --base, base=).
    assert config_base_dir(copy / "config.toml") == copy.resolve()


def test_precomputed_mesh_fixture_reads_its_triangulation(tmp_path: Path, monkeypatch) -> None:
    config = FIXTURES / "run_fast_mf6_precomputed_mesh_input.toml"

    payload = load_toml_with_base_config(config, root=ROOT_CONFIG)

    assert payload["mesh"]["engine"] == "voronoi"
    assert payload["mesh"]["triangle"]["path"] == "mesh/mesh_catchment.msh"
    assert payload["mesh"]["voronoi"]["seeds"] == "triangulation"
    assert "mesh_input" not in payload
    assert "sgrid" not in payload.get("modflow6", {})
    assert payload["domain"]["layers"]["nlay"] == 2
    assert "postprocess" not in payload
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(config)
    assert list(cfg.simulation.process[0].solvers) == ["modflow6"]
    assert cfg.mesh.triangle.path == config.parent / "mesh" / "mesh_catchment.msh"


def test_generated_mesh_fixture_asks_for_voronoi_cells(tmp_path: Path, monkeypatch) -> None:
    config = FIXTURES / "run_fast_mf6_mesh_catchment.toml"

    payload = load_toml_with_base_config(config, root=ROOT_CONFIG)

    assert payload["mesh"]["engine"] == "voronoi"
    assert "mesh_catchment" not in payload
    assert payload["simulation"]["name"] == "example12_fast_mf6_mesh_catchment"
    assert payload["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert payload["simulation"]["process"][1]["solvers"] == ["modflow6"]
    assert payload["simulation"]["time"]["step_value"] == "10 day"
    assert payload["flow"]["first_period_steady"] is False
    assert payload["flow"]["ic"]["kind"] == "top"
    assert payload["flow"]["param"]["K"]["field"]["value"] == "1e-5 m/s"
    assert payload["flow"]["param"]["Sy"]["field"]["value"] == "0.12 -"
    assert payload["data"]["recharge"]["sources"][0]["freq"] == "10D"
    assert "postprocess" not in payload
    assert "analysis" not in payload

    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(config)
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.families.rivers == "cell"
    assert cfg.mesh.families.geology == "face"
    assert cfg.flow.first_period_steady is False


def test_overrides_under_an_old_name_win(tmp_path: Path) -> None:
    from hydromodpy.config.loading import read_document
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
    from hydromodpy.core.toml_io.loader import merge_toml_layers, read_toml_chain
    from hydromodpy.core.toml_io.overrides import env_overrides
    from hydromodpy.project.request import request_of

    base = tmp_path / "base.toml"
    base.write_text(NEW_MF6.format(3.0), encoding="utf-8")
    changes = {"modflow6.process_specific.vka": 5.0}

    with pytest.warns(ConfigKeyRenamedWarning, match="--set: .*write the new name") as told:
        payload = read_document(base, changes=changes, root=ROOT_CONFIG)

    assert payload["solver"]["modflow6"]["process_specific"]["vka"] == 5.0
    assert request_of(base, set=changes).overrides() == {
        "solver.modflow6.process_specific.vka": 5.0
    }
    assert "fix-config" not in str(told[0].message)

    variables = {"HMP_SET_modflow6__process_specific__vka": "7.0"}
    with pytest.warns(ConfigKeyRenamedWarning, match=r"HMP_SET_\*"):
        payload = merge_toml_layers(
            [read_toml_chain(base, root=None)],
            root=ROOT_CONFIG,
            env_overrides=env_overrides(variables),
        )
    assert payload["solver"]["modflow6"]["process_specific"]["vka"] == 7.0


def test_config_from_json_resolves_the_catchment(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    payload = {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path)},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "file", "path": "dem.tif"}]}},
    }

    cfg = HydroModPyConfig.from_json(json.dumps(payload), base_dir=tmp_path)

    assert cfg.data.dem.sources[0].path == dem_path.resolve()


def test_locate_loc_finds_a_key_under_its_section() -> None:
    text = textwrap.dedent(
        """\
        [workspace]

        [flow]
        flow_regime = "steady"
        param_list = ["K", "Sy"]
        """
    )

    line = locate_loc(text, ("flow", "param_list"))

    assert line is not None
    assert text.splitlines()[line - 1].startswith("param_list")


def test_whole_template_is_parseable() -> None:
    # Every skeleton is commented, so adding them must not cost validity.
    parsed = tomllib.loads(generate_toml(root=HydroModPyConfig))

    assert "workflow" in parsed


def test_user_template_has_no_export() -> None:
    # A root array of tables such as [[export]] is a section, not a scalar.
    text = generate_toml(profile="user", root=HydroModPyConfig)

    assert "# [[export]]" in text
    assert "export" not in tomllib.loads(text)


def test_config_from_instances_keeps_its_exports() -> None:
    requests = load_export_requests(
        [{"variables": ["head"], "time": ["last"], "format": "netcdf"}, {"variables": "all"}]
    )
    text = generate_toml_from_instances(
        {"export": requests}, exclude_none=True, root=HydroModPyConfig
    )

    reloaded = load_export_requests(tomllib.loads(text)["export"])

    assert [r.model_dump() for r in reloaded] == [r.model_dump() for r in requests]


def test_config_from_instances_without_exports_has_no_block() -> None:
    text = generate_toml_from_instances({"export": []}, root=HydroModPyConfig)

    assert "[[export]]" not in text


def test_config_meta_marks_export_as_repeated() -> None:
    from hydromodpy.schema.config_schema import build_config_meta

    sections = {entry["name"]: entry for entry in build_config_meta(HydroModPyConfig)["sections"]}

    assert sections["export"]["repeated"] is True
    assert sections["export"]["ref"] == "#/$defs/ExportRequest"
    assert sections["display"]["repeated"] is False


@pytest.mark.parametrize(("base", "overlay", "message"), MERGE_REFUSALS)
def test_merge_refusals(base: dict, overlay: dict, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        merge_toml_payloads(base, overlay)
