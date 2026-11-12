"""A key the register moves warns in a file, the doctor rewrites it, a sealed run reads it.

The frame is played on a register written for the case, whose rows are of a later version and name
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

from hydromodpy.calibration.config_terms import renamed_to
from hydromodpy.config import config_migration as migration
from hydromodpy.config.config_migration import (
    fix_config_chain,
    migrate_config_doc_on_load,
    migrate_sealed_config_doc,
    moved_paths,
    rewrite_dotted_path,
)
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
)
from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.exceptions import ConfigValidationError
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


NO_REWRITE = "This version does not rewrite the file."

# Rows of a later version for keys that exist nowhere in the models: each one is a stand-in move.
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
    assert NO_REWRITE in text
    assert "hmp doctor" not in text


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


WITH_OLD_TABLE = PROJECT + "\n[modflow6.process_specific]\nvka = 2.0\n"
NEW_TABLE = "[solver.modflow6.process_specific]\nvka = 2.0\n"


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
