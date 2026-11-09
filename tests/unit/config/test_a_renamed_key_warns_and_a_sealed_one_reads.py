"""A key the register moves warns in a file, the doctor rewrites it, a sealed run reads it.

The frame is played on a register written for the case, whose rows are of 2.1.0 and name
keys that exist nowhere in the models, passed to the migration as an argument. What reads
a whole file plays on the row the shipped register carries, ``[modflow6]`` to
``[solver.modflow6]``. A key that only a pre-release of 2.0 wrote is refused, and each of
its cases is a line of ``tests/unit/config/test_prerelease_forms.py``.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.calibration.config import renamed_to
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config import config_migration as migration
from hydromodpy.config.config_migration import (
    PRERELEASE_FORMS,
    fix_config_chain,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_layers,
    migrate_sealed_config_doc,
    moved_paths,
    rewrite_dotted_path,
)
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    forget_old_forms_told,
)
from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import read_toml_chain
from hydromodpy.core.toml_io.overrides import SET_SOURCE
from hydromodpy.schema.changes import Register, read
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document

PROJECT = """\
[site]
name = "nancon"
gauge = "NANCON"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem", "hydrography", "hydrometry"]

[[data.dem.sources]]
source = "file"
path = "inputs/DEM_armorican_massif.tif"

[[data.hydrography.sources]]
source = "file"
path = "inputs/nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "file"
path = "inputs/hydrometry"
station_ids = ["NANCON"]

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"

[calibration.outputs.seepage_network.map]
complete = "inputs/nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
"""


WAY_OUT = 'pip install "hydromodpy~=2.0.0"'

# Rows of 2.1.0 for keys that exist nowhere in the models: each one is a stand-in move.
# One more is a key that left, and one is a move that is past its delay. A row of its own,
# which names a rule that cannot rewrite, stands beside them.
ROWS = """\
schema = "hydromodpy.changes.v1"

[[migration]]
document = "config"
old = "calibration.seed_before"
new = "calibration.seed"
since = "2.1.0"

[[migration]]
document = "config"
old = "calibration.phases[*].description_before"
new = "calibration.phases[*].description"
since = "2.1.0"

[[migration]]
document = "config"
old = "calibration.protocol.steady_window_before"
new = "calibration.protocol.steady_window"
since = "2.1.0"

[[migration]]
document = "config"
old = "calibration.parameters.{*}.bounds_before"
new = "calibration.parameters.{*}.bounds"
since = "2.1.0"

[[migration]]
document = "config"
old = "mesh.size_before"
new = "mesh.cell_size"
since = "2.1.0"

[[migration]]
document = "config"
old = "display.overrides.{*}.shade_before"
new = "display.overrides.{*}.cmap"
since = "2.1.0"

[[migration]]
document = "config"
old = "solver.fill_before"
new = "flow.fill_after"
since = "2.1.0"

[[migration]]
document = "config"
old = "geographic.outlet_before"
new = "site.outlet_after"
since = "2.1.0"

[[migration]]
document = "config"
old = "mesh.dropped"
instead = "Write nothing, the key was never read"
sealed = "drop"
since = "2.1.0"

[[migration]]
document = "config"
old = "geographic.late_before"
new = "geographic.late_after"
since = "1.0.0"
"""
FIXTURE = read(ROWS)
STUCK = read(
    'schema = "hydromodpy.changes.v1"\n[[migration]]\ndocument = "config"\n'
    'old = "mesh.stuck_before"\nnew = "mesh.stuck_after"\nrule = "stuck"\nsince = "2.1.0"\n'
)


def _stuck(doc: dict, *, sealed: bool) -> list[str]:
    """A rule that finds the key and cannot carry its value over."""
    del sealed
    if "stuck_before" in doc.get("mesh", {}):
        return [f"mesh.stuck_before{CANNOT_REWRITE}no unit to write"]
    return []


@pytest.fixture(autouse=True)
def _told_again() -> None:
    """A warning is told once per file and key, so each test starts from none told."""
    forget_old_forms_told()


def _project(root: Path) -> Path:
    project = root / "projects" / "nancon"
    for relative in ("DEM_armorican_massif.tif", "nancon_stream_network.gpkg"):
        (project / "inputs" / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / "inputs" / relative).write_bytes(b"x")
    (project / "inputs" / "hydrometry").mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")
    return project


def _doctor(path: Path, register: Register = FIXTURE) -> list[str]:
    """Rewrite the chain of *path* by the rows of the case, and return the changes of *path*."""
    return fix_config_chain(path, register=register)[path.resolve()]


def test_the_message_names_the_new_key_and_the_way_out() -> None:
    text = renamed_to("max_iter", "max_trials", "the evaluations the search may run")

    assert text.startswith("renamed to 'max_trials' (the evaluations the search may run). ")
    assert "max_iter" in text
    assert WAY_OUT in text
    assert "hmp doctor --fix-config" in text


def test_the_doctor_renames_a_key_of_a_section_a_phase_a_protocol_and_a_parameter(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\n"
        "seed_before = 7  # the draw\n"
        "[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n'
        'steady_window_before = { start = "2000-01-01", end = "2000-12-31" }\n'
        "[[calibration.phases]]\n"
        'name = "a"\n'
        'description_before = "first"\n'
        "[[calibration.phases]]\n"
        'name = "b"\n'
        'description_before = "second"\n'
        "[calibration.parameters.K]\n"
        "bounds_before = [1e-6, 1e-3]\n"
        "[calibration.parameters.Sy]\n"
        "bounds = [0.01, 0.3]\n",
        encoding="utf-8",
    )

    changes = _doctor(path)

    written = path.read_text(encoding="utf-8")
    document = tomllib.loads(written)
    assert document["calibration"]["seed"] == 7
    assert "# the draw" in written
    assert document["calibration"]["protocol"]["steady_window"]["start"] == "2000-01-01"
    assert [p["description"] for p in document["calibration"]["phases"]] == ["first", "second"]
    assert document["calibration"]["parameters"]["K"]["bounds"] == [1e-6, 1e-3]
    assert "_before" not in written
    assert len(changes) == 5
    assert _doctor(path) == []


def test_the_doctor_keeps_the_new_name_when_a_key_is_given_under_both(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text("[calibration]\nseed_before = 7\nseed = 8\n", encoding="utf-8")

    changes = _doctor(path)

    assert changes == [
        "calibration.seed_before dropped ([calibration.seed] already set; "
        "it held other values: 7 against 8)"
    ]
    assert tomllib.loads(path.read_text(encoding="utf-8"))["calibration"] == {"seed": 8}


def test_a_value_the_doctor_cannot_carry_over_stays_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(migration.RULES, "stuck", _stuck)
    path = tmp_path / "mesh.toml"
    path.write_text("[mesh]\nstuck_before = 7\n", encoding="utf-8")

    assert _doctor(path, STUCK) == [f"mesh.stuck_before{CANNOT_REWRITE}no unit to write"]
    assert "stuck_before = 7" in path.read_text(encoding="utf-8")


def test_a_dropped_key_is_dropped_in_a_sealed_read_and_refused_in_a_file(
    tmp_path: Path,
) -> None:
    doc = {"mesh": {"dropped": 7}}

    migrate_sealed_config_doc(doc, register=FIXTURE)

    assert doc == {"mesh": {}}
    with pytest.raises(ConfigValidationError, match=r"mesh\.dropped left: it left in 2\.1\.0"):
        migrate_config_doc_on_load({"mesh": {"dropped": 7}}, source="a.toml", register=FIXTURE)


def test_a_dotted_path_of_a_key_that_left_is_not_rewritten() -> None:
    doc = {
        "sites": {"bind": {"mesh.dropped": "n"}},
        "calibration": {"parameters": {"p": {"path": "mesh.dropped"}}},
    }
    before = copy.deepcopy(doc)

    assert migrate_config_doc(doc, register=FIXTURE) == []
    assert doc == before


WITH_OLD_TABLE = PROJECT + "\n[modflow6.process_specific]\nvka = 2.0\n"
NEW_TABLE = "[solver.modflow6.process_specific]\nvka = 2.0\n"


def test_a_moved_table_warns_in_a_file_and_reads_in_silence_in_a_sealed_run_config(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    project = _project(tmp_path)
    user_file = project / "project.toml"
    user_file.write_text(WITH_OLD_TABLE, encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning, match=r"modflow6 -> \[solver\.modflow6\]") as told:
        config = HydroModPyConfig.from_toml(user_file)
    assert held_tables_of(config.solver)["modflow6"].process_specific.vka == 2.0
    assert f"hmp doctor --fix-config {user_file}" in str(told[0].message)

    sealed = project / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text(WITH_OLD_TABLE, encoding="utf-8")
    recwarn.clear()

    config = HydroModPyConfig.from_toml(sealed)

    assert held_tables_of(config.solver)["modflow6"].process_specific.vka == 2.0
    assert not [w for w in recwarn if issubclass(w.category, ConfigKeyRenamedWarning)]


def test_a_file_that_writes_only_current_forms_is_left_alone(tmp_path: Path) -> None:
    """Each current shape sits beside the one a pre-release wrote, and says nothing."""
    document = {
        "export": [{"variables": ["head"], "format": "netcdf", "time": "last"}],
        "flow": {
            "ic": {"kind": "steady_state", "source": "mean_recharge"},
            "bc": {"drainage": {"kind": "drain"}},
            "param": {"K": {"field_vertical_profile": {"kind": "exponential"}}},
        },
        "calibration": {"method_options": {"max_trials": 5}, "window": {"start": "2001-01-01"}},
        "geographic": {"catchment": {"kind": "from_outlet_coord"}},
        "simulation": {"name": "x", "process": [{"id": "flow", "kind": "flow"}]},
    }
    before = copy.deepcopy(document)

    assert migrate_config_doc_on_load(document, source=tmp_path / "project.toml") == []
    assert document == before


def test_a_load_of_a_user_file_does_not_run_the_sealed_rules(tmp_path: Path) -> None:
    doc = {"mesh": {"dropped": 7}}
    with pytest.raises(ConfigValidationError):
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml", register=FIXTURE)
    assert doc == {"mesh": {"dropped": 7}}

    sealed = tmp_path / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text("", encoding="utf-8")
    migrate_config_doc_on_load(doc, source=sealed, register=FIXTURE)
    assert doc == {"mesh": {}}


def test_the_end_of_the_delay_refuses_a_file_and_still_reads_a_sealed_config(
    tmp_path: Path,
) -> None:
    user_file = tmp_path / "project.toml"
    user_file.write_text("[geographic]\nlate_before = 7\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="late_before"):
        migrate_config_doc_on_load(
            tomllib.loads(user_file.read_text(encoding="utf-8")),
            source=user_file,
            register=FIXTURE,
        )
    assert _doctor(user_file) == ["geographic.late_before -> [geographic.late_after]"]
    assert tomllib.loads(user_file.read_text(encoding="utf-8")) == {"geographic": {"late_after": 7}}

    sealed = {"geographic": {"late_before": 7}}
    migrate_sealed_config_doc(sealed, register=FIXTURE)
    assert sealed == {"geographic": {"late_after": 7}}


def test_a_sealed_document_and_a_user_dict_read_under_the_new_name(tmp_path: Path) -> None:
    """A sealed run reads in silence; a dict is read as a file is, with the warning."""
    project = _project(tmp_path)
    document = tomllib.loads(WITH_OLD_TABLE)
    document["workspace"] = {"project_root": str(project)}

    config = HydroModPyConfig.from_snapshot(document)

    assert held_tables_of(config.solver)["modflow6"].process_specific.vka == 2.0
    with pytest.raises(ConfigValidationError, match="project_root is not a key"):
        HydroModPyConfig.from_dict(document, base_dir=project)
    del document["workspace"]
    with pytest.warns(ConfigKeyRenamedWarning, match=r"modflow6 -> \[solver\.modflow6\]"):
        as_a_file = HydroModPyConfig.from_dict(document, base_dir=project)
    assert held_tables_of(as_a_file.solver)["modflow6"].process_specific.vka == 2.0


def test_a_frozen_run_with_a_table_under_its_old_name_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "project.toml").write_text(PROJECT + "\n" + NEW_TABLE, encoding="utf-8")
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = frozen.replace("[solver.modflow6.", "[modflow6.")
    assert old != frozen
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = held_tables_of(cfg.solver)["modflow6"].model_dump(mode="json")
    assert held_tables_of(replayed.solver)["modflow6"].model_dump(mode="json") == expected


def test_a_pre_release_run_is_refused_whether_it_is_sealed_or_not(tmp_path: Path) -> None:
    """A run sealed by a pre-release of 2.0 is refused with the way out, as its project file is."""
    project = _project(tmp_path)
    form = "calibration.outputs.{*}.observed_network"
    assert form in {known.path for known in PRERELEASE_FORMS}
    document = tomllib.loads(PROJECT)
    document["calibration"]["outputs"]["seepage_network"]["observed_network"] = "dem_network"
    text = tomlkit.dumps(document)
    sealed = project / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text(text, encoding="utf-8")
    (project / "project.toml").write_text(text, encoding="utf-8")

    for source in (sealed, project / "project.toml"):
        with pytest.raises(ConfigValidationError, match="written by a pre-release") as refused:
            HydroModPyConfig.from_toml(source)
        assert "calibration.outputs.seepage_network.observed_network" in str(refused.value)
        assert WAY_OUT in str(refused.value)


def test_a_moved_table_keeps_its_comments(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        "[modflow6.process_specific]\nvka = 2.0  # the step\n\n[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n',
        encoding="utf-8",
    )

    assert migration.fix_config_file(path) == ["modflow6 -> [solver.modflow6]"]

    written = path.read_text(encoding="utf-8")
    assert "vka = 2.0  # the step" in written
    assert "[modflow6" not in written.replace("[solver.modflow6", "")
    assert tomllib.loads(written)["solver"]["modflow6"]["process_specific"] == {"vka": 2.0}


def test_a_key_renamed_in_its_own_table_keeps_its_place_and_its_comment(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[display.overrides.map]\nfirst = 1\nshade_before = "a"  # the map\nlast = 2\n',
        encoding="utf-8",
    )

    assert _doctor(path) == ["display.overrides.map.shade_before -> cmap"]

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line.split(" ")[0] for line in lines[1:]] == ["first", "cmap", "last"]
    assert lines[2].endswith("# the map")


def test_a_comment_survives_in_a_document_the_doctor_wrote() -> None:
    doc = tomlkit.parse("[calibration]\nseed_before = 7  # fixed\n")

    migrate_config_doc(doc, register=FIXTURE)

    assert "seed = 7  # fixed" in tomlkit.dumps(doc)


# One row per kind of rename, each new to the schema, as a lot of renames will add.
CELL, OPTION, FILL, OUTLET = (
    next(row for row in FIXTURE.migrations if row.old == old)
    for old in (
        "mesh.size_before",
        "display.overrides.{*}.shade_before",
        "solver.fill_before",
        "geographic.outlet_before",
    )
)


def _phase(overrides: dict) -> dict:
    return {"calibration": {"phases": [{"name": "one", "overrides": overrides}]}}


PLACES = {
    "the key itself": ({"mesh": {"size_before": 1}}, {"mesh": {"cell_size": 1}}),
    "a directive of the key": (
        {"mesh": {"size_before__delete": True}},
        {"mesh": {"cell_size__delete": True}},
    ),
    "a key that changes table": (
        {"solver": {"fill_before": True}},
        {"flow": {"fill_after": True}},
    ),
    "a table that changes place": (
        {"geographic": {"outlet_before": {"x": 1}}},
        {"site": {"outlet_after": {"x": 1}}},
    ),
    "a figure option": (
        {"display": {"overrides": {"seepage_map": {"shade_before": "a"}}}},
        {"display": {"overrides": {"seepage_map": {"cmap": "a"}}}},
    ),
    "a phase override": (_phase({"mesh.size_before": 1}), _phase({"mesh.cell_size": 1})),
    "a phase override under a moved table": (
        _phase({"geographic.outlet_before.x": 1}),
        _phase({"site.outlet_after.x": 1}),
    ),
    "a phase override of a figure": (
        _phase({"display.overrides.seepage_map.shade_before": "a"}),
        _phase({"display.overrides.seepage_map.cmap": "a"}),
    ),
    "a phase override written as tables": (
        _phase({"mesh": {"size_before": 1}}),
        _phase({"mesh": {"cell_size": 1}}),
    ),
    "a phase a child adds": (
        {"calibration": {"phases__append": [{"overrides": {"mesh.size_before": 1}}]}},
        {"calibration": {"phases__append": [{"overrides": {"mesh.cell_size": 1}}]}},
    ),
    "a phase a child merges": (
        {"calibration": {"phases__merge": [{"name": "a", "overrides": {"mesh.size_before": 1}}]}},
        {"calibration": {"phases__merge": [{"name": "a", "overrides": {"mesh.cell_size": 1}}]}},
    ),
    "the path of a parameter": (
        {"calibration": {"parameters": {"p": {"path": "mesh.size_before"}}}},
        {"calibration": {"parameters": {"p": {"path": "mesh.cell_size"}}}},
    ),
    "the target of a parameter": (
        {"calibration": {"parameters": {"p": {"target": "solver.fill_before"}}}},
        {"calibration": {"parameters": {"p": {"target": "flow.fill_after"}}}},
    ),
    "a bind line": (
        {"sites": {"bind": {"mesh.size_before": "size"}}},
        {"sites": {"bind": {"mesh.cell_size": "size"}}},
    ),
    "the set table of a recipe": (
        {"sites": {"recipes": {"r": {"set": {"mesh.size_before": 2}}}}},
        {"sites": {"recipes": {"r": {"set": {"mesh.cell_size": 2}}}}},
    ),
}


@pytest.mark.parametrize(("written", "expected"), PLACES.values(), ids=PLACES.keys())
def test_one_row_of_a_table_rewrites_every_place_a_path_is_written(
    written: dict, expected: dict
) -> None:
    doc = copy.deepcopy(written)

    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(doc, source="a_file.toml", register=FIXTURE)

    assert doc == expected


def test_one_row_reaches_the_command_line_and_the_helpers() -> None:
    def moved(path: str) -> str:
        return rewrite_dotted_path(path, register=FIXTURE)

    assert moved("mesh.size_before") == "mesh.cell_size"
    assert moved("solver.fill_before") == "flow.fill_after"
    assert moved("geographic.outlet_before.x") == "site.outlet_after.x"
    assert moved("display.overrides.a_map.shade_before") == "display.overrides.a_map.cmap"
    assert moved("mesh.size_before__delete") == "mesh.cell_size__delete"
    assert moved("mesh.cell_size") == "mesh.cell_size"
    assert CELL in {moved_path.row for moved_path in moved_paths(register=FIXTURE)}


def test_a_set_on_the_command_line_follows_the_row(tmp_path: Path) -> None:
    from hydromodpy.config.loading import read_document
    from hydromodpy.project.request import RunRequest

    base = tmp_path / "base.toml"
    base.write_text(NEW_TABLE, encoding="utf-8")
    changes = {"modflow6.process_specific.vka": 3.0}

    with pytest.warns(ConfigKeyRenamedWarning, match="--set"):
        payload = read_document(base, changes=changes, root=ROOT_CONFIG)

    assert payload == {"solver": {"modflow6": {"process_specific": {"vka": 3.0}}}}
    assert RunRequest(config=payload, set=changes).overrides() == {
        "solver.modflow6.process_specific.vka": 3.0
    }


def test_the_doctor_follows_the_row_everywhere_and_keeps_the_comments(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        "# the sites\n"
        "[sites.bind]\n"
        '"mesh.size_before" = "size" # a column\n'
        "\n"
        "[calibration.parameters.p]\n"
        'path = "mesh.size_before" # moved by the search\n'
        "\n"
        "[[calibration.phases]]\n"
        'name = "one"\n'
        "[calibration.phases.overrides]\n"
        '"solver.fill_before" = true # a phase\n',
        encoding="utf-8",
    )

    changes = _doctor(path)

    assert len(changes) == 3
    text = path.read_text()
    for comment in ("# the sites", "# a column", "# moved by the search", "# a phase"):
        assert comment in text
    written = tomllib.loads(text)
    assert written["sites"]["bind"] == {"mesh.cell_size": "size"}
    assert written["calibration"]["parameters"]["p"]["path"] == "mesh.cell_size"
    assert written["calibration"]["phases"][0]["overrides"] == {"flow.fill_after": True}


def test_a_project_file_reads_its_bind_lines_under_the_new_name(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        tomlkit.dumps({"sites": {"bind": {"modflow6.process_specific.vka": "k"}}}), encoding="utf-8"
    )

    with pytest.warns(ConfigKeyRenamedWarning):
        chain = read_toml_chain(path, root=ROOT_CONFIG)

    assert chain[-1].own == {"sites": {"bind": {"solver.modflow6.process_specific.vka": "k"}}}


def test_a_set_from_no_file_has_no_file_to_rewrite() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as told:
        migrate_layers([(SET_SOURCE, {"modflow6": {"process_specific": {"vka": 3.0}}})])

    message = str(told[0].message)
    assert "write the new name" in message
    assert "hmp doctor" not in message
