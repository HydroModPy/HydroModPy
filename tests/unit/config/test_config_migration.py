"""Migration of a configuration document by the rows of the register of changes.

A row is played on a live file in its delay (it warns), past its delay (it is refused with
the new name), on a sealed run (it reads in silence), by the doctor (it rewrites the file)
and on a dotted path. Most cases use registers written for the case, passed as an argument,
whose rows name keys that exist nowhere in the models. The loader and the doctor are also
played on rows the shipped register carries, such as ``[modflow6]`` to ``[solver.modflow6]``.
"""

from __future__ import annotations

import copy
import tomllib
import warnings
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.calibration.config_terms import renamed_to
from hydromodpy.config import config_migration as migration
from hydromodpy.config.config_migration import (
    apply_edition,
    fix_config_chain,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_merged_doc,
    migrate_sealed_config_doc,
    moved_paths,
    rewrite_dotted_path,
)
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    warn_old_form,
)
from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.version import __version__
from hydromodpy.schema.changes import Register, migrations_of, outlived, read
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document

HEAD = 'schema = "hydromodpy.changes.v1"\n'
NO_REWRITE = "This version does not rewrite the file."

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
NEW_TABLE = "[solver.modflow6.process_specific]\nvka = 2.0\n"
MODFLOW6 = "[modflow6.process_specific]\nvka = 2.0\n"


def _write(tmp_path: Path, body: str, name: str = "project.toml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _chain(tmp_path: Path, parent: str, child: str) -> tuple[Path, Path]:
    """Write a parent and a child that inherits it, and return both paths."""
    first = _write(tmp_path, parent, "parent.toml")
    second = _write(tmp_path, f'base_config = "parent.toml"\n{child}', "child.toml")
    return first, second


def _project(root: Path) -> Path:
    project = root / "projects" / "nancon"
    for relative in ("DEM_armorican_massif.tif", "nancon_stream_network.gpkg"):
        (project / "inputs" / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / "inputs" / relative).write_bytes(b"x")
    (project / "inputs" / "hydrometry").mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")
    return project


def _steps(path: str) -> list[str]:
    """Split a form path into keys, with ``{*}`` as the free name ``x`` and ``[*]`` as an index."""
    steps: list[str] = []
    for part in path.split("."):
        if part == "{*}":
            steps.append("x")
            continue
        steps.append(part.removesuffix("[*]"))
        if part.endswith("[*]"):
            steps.append("[0]")
    return steps


def _document_with(path: str, value: object) -> dict:
    """Return a document that holds *value* at *path*, a table of a list or a free name included."""
    steps = _steps(path)
    root: dict = {}
    node: object = root
    for index, step in enumerate(steps):
        last = index == len(steps) - 1
        following = steps[index + 1] if not last else ""
        if step == "[0]":
            continue
        child: object = value if last else ([{}] if following == "[0]" else {})
        node[step] = child  # type: ignore[index]
        node = child[0] if isinstance(child, list) else child
    return root


def _dig(doc: object, path: str) -> object:
    for step in _steps(path):
        doc = doc[0] if step == "[0]" else doc[step]  # type: ignore[index]
    return doc


def _holds(doc: object, path: str) -> bool:
    try:
        _dig(doc, path)
    except (KeyError, IndexError, TypeError):
        return False
    return True


# Register of the rename cases. Each row is a move that exists nowhere in the models.
# One row is a key that left, and one is a move that is past its delay.
RENAMES = read(
    HEAD
    + """\
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
)
STUCK = read(
    HEAD
    + '[[migration]]\ndocument = "config"\nold = "mesh.stuck_before"\n'
    + 'new = "mesh.stuck_after"\nrule = "stuck"\nsince = "2.1.0"\n'
)

# One row per kind of rename, each new to the schema, as a lot of renames will add.
CELL, OPTION, FILL, OUTLET = (
    next(row for row in RENAMES.migrations if row.old == old)
    for old in (
        "mesh.size_before",
        "display.overrides.{*}.shade_before",
        "solver.fill_before",
        "geographic.outlet_before",
    )
)

# Register of the shape cases: a table that moves, a key renamed in each table of a list,
# a value renamed, a move past its delay and two keys that left.
SHAPES_REGISTER = read(
    HEAD
    + '[[migration]]\ndocument = "config"\nold = "old_table"\nnew = "new.table"\nsince = "2.1.0"\n'
    + '[[migration]]\ndocument = "config"\nold = "items[*].type"\nnew = "items[*].kind"\n'
    + 'since = "2.1.0"\n'
    + '[[migration]]\ndocument = "config"\nkey = "section.kind"\nold_value = "a"\n'
    + 'new_value = "b"\nsince = "2.1.0"\n'
    + '[[migration]]\ndocument = "config"\nold = "late_table"\nnew = "late.table"\nsince = "1.0.0"\n'
    + '[[migration]]\ndocument = "config"\nold = "section.gone"\n'
    + 'instead = "Nothing replaces it."\nsealed = "drop"\nsince = "2.1.0"\n'
    + '[[migration]]\ndocument = "config"\nold = "section.left"\n'
    + 'instead = "Write section.right instead."\nsince = "2.1.0"\n'
)

# Register of the editions: two defaults that moved in edition 2.1.
EDITIONS = read(
    HEAD
    + '[[default]]\nid = "d"\nsince = "2.1.0"\nedition = "2.1"\nkey = "solver.x"\nold = 0.5\n'
    + 'new = 0.45\nquantities = ["metrics"]\ntext = "t"\n'
    + '[[default]]\nid = "e"\nsince = "2.1.0"\nedition = "2.1"\nkey = "flow.bc.{*}.y"\n'
    + 'old = 1\nnew = 2\nquantities = ["metrics"]\ntext = "t"\n'
)

FORWARD_MODEL_REFUSAL = (
    "a forward model is a solver backend since 2.0.0: name it by solver.backend, register "
    "it in the hydromodpy.solver entry-point group, and calibrate it with the pipeline evaluator"
)


def _stuck(doc: dict, *, sealed: bool) -> list[str]:
    """A rule that finds the key and cannot carry its value over."""
    del sealed
    if "stuck_before" in doc.get("mesh", {}):
        return [f"mesh.stuck_before{CANNOT_REWRITE}no unit to write"]
    return []


def _doctor(path: Path, register: Register = RENAMES) -> list[str]:
    """Rewrite the chain of *path* by the rows of the case and return its changes."""
    return fix_config_chain(path, register=register)[path.resolve()]


def _phase(overrides: dict) -> dict:
    return {"calibration": {"phases": [{"name": "one", "overrides": overrides}]}}


def test_renamed_message():
    text = renamed_to("max_iter", "max_trials", "the evaluations the search may run")

    assert text.startswith("renamed to 'max_trials' (the evaluations the search may run). ")
    assert "max_iter" in text
    assert NO_REWRITE in text
    assert "hmp doctor" not in text


def test_no_doctor_promise() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="seed left: why") as told:
        warn_old_form("project.toml", "calibration.seed left: why")
    assert "hmp doctor" not in str(told[0].message)


SHAPES = [
    pytest.param(
        "[old_table]\nx = 1\n",
        "new.table.x",
        1,
        "old_table -> [new.table]",
        id="a table that moves",
    ),
    pytest.param(
        '[[items]]\ntype = "flow"\n',
        "items[*].kind",
        "flow",
        "items[0].type -> kind",
        id="a key renamed in each table of a list",
    ),
    pytest.param(
        '[section]\nkind = "a"\n',
        "section.kind",
        "b",
        "section.kind: 'a' -> 'b'",
        id="a value renamed",
    ),
]


@pytest.mark.parametrize(("text", "path", "value", "told"), SHAPES)
def test_doctor_rewrites_each_shape(
    text: str, path: str, value: object, told: str, tmp_path: Path
) -> None:
    file = _write(tmp_path, text)

    assert fix_config_chain(file, register=SHAPES_REGISTER)[file.resolve()] == [told]
    assert _dig(tomllib.loads(file.read_text(encoding="utf-8")), path) == value
    assert fix_config_chain(file, register=SHAPES_REGISTER)[file.resolve()] == []


def test_doctor_renames_calibration(tmp_path: Path) -> None:
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


def test_doctor_keeps_new_name(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text("[calibration]\nseed_before = 7\nseed = 8\n", encoding="utf-8")

    changes = _doctor(path)

    assert changes == [
        "calibration.seed_before dropped ([calibration.seed] already set; "
        "it held other values: 7 against 8)"
    ]
    assert tomllib.loads(path.read_text(encoding="utf-8"))["calibration"] == {"seed": 8}


def test_doctor_stuck_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(migration.RULES, "stuck", _stuck)
    path = tmp_path / "mesh.toml"
    path.write_text("[mesh]\nstuck_before = 7\n", encoding="utf-8")

    assert _doctor(path, STUCK) == [f"mesh.stuck_before{CANNOT_REWRITE}no unit to write"]
    assert "stuck_before = 7" in path.read_text(encoding="utf-8")


def test_doctor_keeps_comment(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[display.overrides.map]\nfirst = 1\nshade_before = "a"  # the map\nlast = 2\n',
        encoding="utf-8",
    )

    assert _doctor(path) == ["display.overrides.map.shade_before -> cmap"]

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line.split(" ")[0] for line in lines[1:]] == ["first", "cmap", "last"]
    assert lines[2].endswith("# the map")


def test_doctor_follows_row(tmp_path: Path) -> None:
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


def test_dry_run(tmp_path: Path) -> None:
    path = _write(tmp_path, MODFLOW6)
    diffs: dict[Path, str] = {}

    changes = fix_config_chain(path, dry_run=True, diffs=diffs)

    assert changes[path.resolve()] == ["modflow6 -> [solver.modflow6]"]
    assert path.read_text() == MODFLOW6
    assert "+[solver.modflow6.process_specific]" in diffs[path.resolve()]


def test_backend_split_in_two_files(tmp_path: Path) -> None:
    # kind = "custom" in a parent and name in a child say the name only together.
    _, child = _chain(
        tmp_path, '[solver.backend]\nkind = "custom"\n', '[solver.backend]\nname = "plugged"\n'
    )

    with pytest.warns(ConfigKeyRenamedWarning, match="solver.backend.kind -> solver.backend"):
        merged = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert merged["solver"]["backend"] == "plugged"


def test_form_past_delay_refused(tmp_path: Path) -> None:
    assert outlived("1.0.0", __version__)
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(
            tomllib.loads("[late_table]\nx = 1\n"), source=source, register=SHAPES_REGISTER
        )

    assert str(refused.value) == (
        f"{source}: late_table -> [late.table]. This old form is refused; "
        f"`hmp doctor --fix-config {source}` rewrites the file."
    )


# Each row: the file text, the label of the key, and the document left after a sealed read
# (None when the row has no drop and a sealed read refuses).
RETIRED = [
    pytest.param(
        "[section]\ngone = 1\nkept = 2\n",
        "section.gone",
        {"section": {"kept": 2}},
        id="a key that left, sealed drop",
    ),
    pytest.param(
        "[section]\nleft = 1\n", "section.left", None, id="a key that left with nothing to drop"
    ),
]


@pytest.mark.parametrize(("text", "label", "sealed"), RETIRED)
def test_sealed_drop_of_a_left_key(text: str, label: str, sealed: object) -> None:
    doc = tomllib.loads(text)
    if sealed is None:
        with pytest.raises(ConfigValidationError, match=f"a sealed run config holds {label}"):
            migrate_sealed_config_doc(doc, register=SHAPES_REGISTER)
        return

    assert migrate_sealed_config_doc(doc, register=SHAPES_REGISTER) == [f"{label} dropped (sealed)"]
    assert doc == sealed


@pytest.mark.parametrize(("text", "label", "sealed"), RETIRED)
def test_doctor_leaves_a_left_key(text: str, label: str, sealed: object, tmp_path: Path) -> None:
    del sealed
    file = _write(tmp_path, text)

    changes = fix_config_chain(file, register=SHAPES_REGISTER)[file.resolve()]

    assert file.read_text() == text
    assert len(changes) == 1 and changes[0].startswith(f"{label}{CANNOT_REWRITE}")


def test_dropped_key() -> None:
    doc = {"mesh": {"dropped": 7}}

    migrate_sealed_config_doc(doc, register=RENAMES)

    assert doc == {"mesh": {}}
    with pytest.raises(ConfigValidationError, match=r"mesh\.dropped left: it left in 2\.1\.0"):
        migrate_config_doc_on_load({"mesh": {"dropped": 7}}, source="a.toml", register=RENAMES)


def test_user_file_skips_sealed_rules(tmp_path: Path) -> None:
    doc = {"mesh": {"dropped": 7}}
    with pytest.raises(ConfigValidationError):
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml", register=RENAMES)
    assert doc == {"mesh": {"dropped": 7}}

    sealed = tmp_path / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text("", encoding="utf-8")
    migrate_config_doc_on_load(doc, source=sealed, register=RENAMES)
    assert doc == {"mesh": {}}


def test_frozen_run_old_table(tmp_path: Path) -> None:
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


DOTTED = [
    pytest.param(
        {"calibration": {"phases": [{"name": "p", "overrides": {"old_table.x": 1}}]}},
        ("calibration", "phases", 0, "overrides"),
        {"new.table.x": 1},
        id="a phase override",
    ),
    pytest.param(
        {"calibration": {"phases": [{"name": "p", "overrides": {"old_table": {"x": 1}}}]}},
        ("calibration", "phases", 0, "overrides"),
        {"new.table": {"x": 1}},
        id="a phase override written as tables",
    ),
    pytest.param(
        {"sites": {"bind": {"old_table.x": "column"}}},
        ("sites", "bind"),
        {"new.table.x": "column"},
        id="a bind line",
    ),
    pytest.param(
        {"sites": {"recipes": {"r": {"set": {"old_table.x": 1}}}}},
        ("sites", "recipes", "r", "set"),
        {"new.table.x": 1},
        id="a recipe",
    ),
    pytest.param(
        {"calibration": {"parameters": {"k": {"path": "old_table.x"}}}},
        ("calibration", "parameters", "k"),
        {"path": "new.table.x"},
        id="a calibration parameter",
    ),
]


@pytest.mark.parametrize(("doc", "where", "after"), DOTTED)
def test_dotted_path_follows_table(doc: dict, where: tuple, after: dict) -> None:
    migrate_config_doc(doc, register=SHAPES_REGISTER)

    node: object = doc
    for step in where:
        node = node[step]  # type: ignore[index]
    assert node == after
    assert rewrite_dotted_path("old_table.x", register=SHAPES_REGISTER) == "new.table.x"


def test_dotted_key_given_twice() -> None:
    bind = {"old_table.x": "a", "new.table.x": "b"}

    changes = migrate_config_doc({"sites": {"bind": bind}}, register=SHAPES_REGISTER)

    assert bind == {"old_table.x": "a", "new.table.x": "b"}
    assert changes == [
        f'sites.bind."old_table.x"{CANNOT_REWRITE}"new.table.x" is given too, keep one'
    ]


def test_key_under_both_names() -> None:
    doc = {"old_table": {"x": 1}, "new": {"table": {"x": 2}}}

    changes = migrate_config_doc(doc, register=SHAPES_REGISTER)

    assert doc == {"new": {"table": {"x": 2}}}
    assert changes == [
        "old_table dropped ([new.table] already set; it held other values: x = 1 against 2)"
    ]


def test_directive_of_a_moved_table() -> None:
    doc = {"old_table__delete": True, "items__append": [{"type": "flow"}]}

    changes = migrate_config_doc(doc, register=SHAPES_REGISTER)

    assert doc == {"new": {"table__delete": True}, "items__append": [{"kind": "flow"}]}
    assert "old_table__delete -> new.table__delete" in changes


# Each case is a place where a path is written, as the document has it and as it is rewritten.
PLACES = [
    pytest.param({"mesh": {"size_before": 1}}, {"mesh": {"cell_size": 1}}, id="the key itself"),
    pytest.param(
        {"mesh": {"size_before__delete": True}},
        {"mesh": {"cell_size__delete": True}},
        id="a directive of the key",
    ),
    pytest.param(
        {"solver": {"fill_before": True}},
        {"flow": {"fill_after": True}},
        id="a key that changes table",
    ),
    pytest.param(
        {"geographic": {"outlet_before": {"x": 1}}},
        {"site": {"outlet_after": {"x": 1}}},
        id="a table that changes place",
    ),
    pytest.param(
        {"display": {"overrides": {"seepage_map": {"shade_before": "a"}}}},
        {"display": {"overrides": {"seepage_map": {"cmap": "a"}}}},
        id="a figure option",
    ),
    pytest.param(
        _phase({"mesh.size_before": 1}), _phase({"mesh.cell_size": 1}), id="a phase override"
    ),
    pytest.param(
        _phase({"geographic.outlet_before.x": 1}),
        _phase({"site.outlet_after.x": 1}),
        id="a phase override under a moved table",
    ),
    pytest.param(
        _phase({"display.overrides.seepage_map.shade_before": "a"}),
        _phase({"display.overrides.seepage_map.cmap": "a"}),
        id="a phase override of a figure",
    ),
    pytest.param(
        _phase({"mesh": {"size_before": 1}}),
        _phase({"mesh": {"cell_size": 1}}),
        id="a phase override written as tables",
    ),
    pytest.param(
        {"calibration": {"phases__append": [{"overrides": {"mesh.size_before": 1}}]}},
        {"calibration": {"phases__append": [{"overrides": {"mesh.cell_size": 1}}]}},
        id="a phase a child adds",
    ),
    pytest.param(
        {"calibration": {"phases__merge": [{"name": "a", "overrides": {"mesh.size_before": 1}}]}},
        {"calibration": {"phases__merge": [{"name": "a", "overrides": {"mesh.cell_size": 1}}]}},
        id="a phase a child merges",
    ),
    pytest.param(
        {"calibration": {"parameters": {"p": {"path": "mesh.size_before"}}}},
        {"calibration": {"parameters": {"p": {"path": "mesh.cell_size"}}}},
        id="the path of a parameter",
    ),
    pytest.param(
        {"calibration": {"parameters": {"p": {"target": "solver.fill_before"}}}},
        {"calibration": {"parameters": {"p": {"target": "flow.fill_after"}}}},
        id="the target of a parameter",
    ),
    pytest.param(
        {"sites": {"bind": {"mesh.size_before": "size"}}},
        {"sites": {"bind": {"mesh.cell_size": "size"}}},
        id="a bind line",
    ),
    pytest.param(
        {"sites": {"recipes": {"r": {"set": {"mesh.size_before": 2}}}}},
        {"sites": {"recipes": {"r": {"set": {"mesh.cell_size": 2}}}}},
        id="the set table of a recipe",
    ),
]


@pytest.mark.parametrize(("written", "expected"), PLACES)
def test_row_rewrites_every_place(written: dict, expected: dict) -> None:
    doc = copy.deepcopy(written)

    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(doc, source="a_file.toml", register=RENAMES)

    assert doc == expected


def test_row_reaches_the_helpers() -> None:
    def moved(path: str) -> str:
        return rewrite_dotted_path(path, register=RENAMES)

    assert moved("mesh.size_before") == "mesh.cell_size"
    assert moved("solver.fill_before") == "flow.fill_after"
    assert moved("geographic.outlet_before.x") == "site.outlet_after.x"
    assert moved("display.overrides.a_map.shade_before") == "display.overrides.a_map.cmap"
    assert moved("mesh.size_before__delete") == "mesh.cell_size__delete"
    assert moved("mesh.cell_size") == "mesh.cell_size"
    assert CELL in {moved_path.row for moved_path in moved_paths(register=RENAMES)}


APPLIED = [
    pytest.param(
        {"flow": {"bc": {"r": {}}}},
        "2.0",
        {"flow": {"bc": {"r": {"y": 1}}}, "solver": {"x": 0.5}},
        ["solver.x", "flow.bc.r.y"],
        id="an older edition, the key not written",
    ),
    pytest.param(
        {"solver": {"x": 0.7}},
        "2.0",
        {"solver": {"x": 0.7}},
        [],
        id="an older edition, the key written",
    ),
    pytest.param({}, "2.1", {}, [], id="the edition of the default"),
]


@pytest.mark.parametrize(("doc", "edition", "after", "written"), APPLIED)
def test_file_keeps_edition_defaults(
    doc: dict, edition: str, after: dict, written: list[str]
) -> None:
    assert apply_edition(doc, edition=edition, register=EDITIONS) == written
    assert doc == after


def test_merged_and_sealed_editions() -> None:
    merged: dict = {}
    sealed: dict = {"edition": "2.1"}

    migrate_merged_doc(merged, register=EDITIONS)
    migrate_sealed_config_doc(sealed, register=EDITIONS)

    assert merged == {"solver": {"x": 0.5}}
    assert sealed == {"edition": "2.1"}


def test_unknown_edition_refused() -> None:
    doc: dict = {"edition": "9.9"}

    with pytest.raises(ConfigValidationError, match="serves 2.0, 2.1") as refused:
        apply_edition(doc, edition="9.9", register=EDITIONS)

    assert doc == {"edition": "9.9"}
    assert [entry["pointer"] for entry in refused.value.details] == ["/edition"]
    with pytest.raises(ConfigValidationError, match="edition names '9.9'"):
        migrate_merged_doc({"edition": "9.9"}, register=EDITIONS)


def test_edition_optional_section() -> None:
    doc: dict = {"flow": {"bc": {}}}

    written = apply_edition(doc, edition="2.0", register=EDITIONS, optional_sections={"solver"})

    assert written == []
    assert doc == {"flow": {"bc": {}}}
    kept: dict = {"solver": {}}
    assert apply_edition(kept, edition="2.0", register=EDITIONS, optional_sections={"solver"}) == [
        "solver.x"
    ]


CONFIG_MOVES = [row for row in migrations_of("config") if row.shape == "move"]


@pytest.mark.parametrize(
    "row",
    [row for row in CONFIG_MOVES if row.rule is None],
    ids=lambda row: f"{row.old}->{row.new}",
)
def test_doctor_rewrites_every_move(row, tmp_path: Path) -> None:
    path = _write(tmp_path, tomlkit.dumps(_document_with(str(row.old), "probe-value")))

    fix_config_file(path)

    after = tomllib.loads(path.read_text(encoding="utf-8"))
    assert _dig(after, rewrite_dotted_path(str(row.new), sealed=True)) == "probe-value"
    assert not _holds(after, str(row.old))
    assert fix_config_file(path) == []


def test_transport_move_order() -> None:
    olds = [row.old for row in CONFIG_MOVES]

    for name in ("modflow6gwt", "modflow6prt"):
        assert olds.index(f"transport.{name}.parameters") < olds.index(f"transport.{name}")


# Pairs of an old dotted path and the path it becomes, in a phase override and a parameter.
SOLVER_PATHS = [
    ("modflow6.process_specific.vka", "solver.modflow6.process_specific.vka"),
    ("modflownwt.runtime.nwt.headtol", "solver.modflow_nwt.runtime.nwt.headtol"),
    ("flow.runtime.max_iterations", "solver.boussinesq.max_iterations"),
    ("solver.backend.kind", "solver.backend"),
    ("transport.mt3dms.parameters.porosity", "transport.mt3dms.porosity"),
]


@pytest.mark.parametrize(("old", "new"), SOLVER_PATHS)
def test_dotted_path_of_2_0_forms(old: str, new: str) -> None:
    doc = {
        "calibration": {
            "phases": [{"name": "p", "overrides": {old: "probe"}}],
            "parameters": {"vka": {"path": old}},
        }
    }

    migrate_config_doc(doc)

    assert rewrite_dotted_path(old) == new
    assert doc["calibration"]["phases"][0]["overrides"] == {new: "probe"}
    assert doc["calibration"]["parameters"]["vka"]["path"] == new


def test_plugin_backend_dotted_keys() -> None:
    doc = {
        "sites": {
            "recipes": {
                "r": {"set": {"solver.backend.kind": "custom", "solver.backend.name": "plugged"}}
            }
        }
    }

    migrate_config_doc(doc)

    assert doc["sites"]["recipes"]["r"]["set"] == {"solver.backend": "plugged"}


def test_transport_beside_parameters() -> None:
    doc = tomllib.loads(
        "[transport.modpath]\ntrack_dir = 'forward'\n"
        "[transport.modpath.parameters]\ntrack_dir = 'backward'\n"
    )

    changes = migrate_config_doc(doc)

    assert doc["transport"]["modpath"] == {"track_dir": "forward"}
    assert any(
        "transport.modpath.parameters dropped ([transport.modpath] already set" in c
        for c in changes
    )


def test_empty_transport_parent_dropped() -> None:
    doc = {"transport": {"modflow6gwt": {}, "modflow6": {"porosity": 0.2}}}

    changes = migrate_config_doc(doc)

    assert doc == {"transport": {"modflow6": {"porosity": 0.2}}}
    assert changes == [
        "transport.modflow6gwt dropped ([transport.modflow6] already set; it was empty)"
    ]


def test_source_kind_renamed() -> None:
    doc = {"data": {"dem": {"sources": [{"source": "custom", "path": "inputs/dem.tif"}]}}}

    changes = migrate_config_doc(doc)

    assert doc["data"]["dem"]["sources"][0]["source"] == "file"
    assert changes == ["data.dem.sources[0].source: 'custom' -> 'file'"]


def test_doctor_writes_dem_row(tmp_path: Path) -> None:
    path = _write(
        tmp_path, '[geographic.catchment]\nkind = "dem"\ndem_init_path = "inputs/dem.tif"\n'
    )

    told = fix_config_file(path)

    assert told == [
        "geographic.catchment.dem_init_path -> [[data.dem.sources]] path 'inputs/dem.tif' "
        "(dem_init_path was removed in 2.0.0: declare the DEM as [[data.dem.sources]] "
        'with source = "file" and the same path)'
    ]
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["data"]["dem"]["sources"] == [{"source": "file", "path": "inputs/dem.tif"}]
    assert "dem_init_path" not in parsed["geographic"]["catchment"]


def test_sealed_dem_init_path() -> None:
    doc = {"geographic": {"catchment": {"dem_init_path": "inputs/dem.tif"}}}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        migrate_sealed_config_doc(doc)

    assert doc["data"] == {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}}
    assert "catchment" not in doc["geographic"]


def test_scored_evaluator_dropped(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, '[calibration]\nevaluator = "scored_forward_model"\n')

    told = fix_config_file(path)

    assert told == [f"calibration.evaluator dropped: {FORWARD_MODEL_REFUSAL}"]
    assert "evaluator" not in tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert fix_config_file(path) == []


def test_sealed_null_forward_model() -> None:
    doc = {"calibration": {"forward_model": None}}

    migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {}}


def test_sealed_forward_model_name_warns() -> None:
    doc = {"calibration": {"forward_model": "linear_reservoir"}}

    with pytest.warns(ConfigKeyRenamedWarning, match="calibration.forward_model retired"):
        migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {}}


FROZEN_V1 = Path(__file__).parent / "fixtures" / "frozen_run_config_export_v1.toml"

# Each row: the file text and the parts of the message that name the fix.
DOCTOR_REFUSALS = [
    pytest.param(
        '[geographic.catchment]\nkind = "dem"\ndem_init_path = "inputs/dem.tif"\n',
        [
            "dem_init_path was removed in 2.0.0",
            "[[data.dem.sources]]",
            'source = "file"',
        ],
        id="dem_init_path",
    ),
    pytest.param(
        '[geographic.catchment]\nkind = "dem"\n'
        '[[data.dem.sources]]\nsource = "file"\npath = "dem.tif"\n',
        ["'dem.tif' is a bare name", "inputs/dem.tif"],
        id="a bare name",
    ),
]


@pytest.mark.parametrize(("text", "named"), DOCTOR_REFUSALS)
def test_doctor_refusals(text: str, named: list[str], tmp_path: Path) -> None:
    from hydromodpy.project.doctor import refusal_of

    refusal = refusal_of(_write(tmp_path, text))

    assert refusal is not None
    for part in named:
        assert part in str(refusal)


def test_forward_model_refused_on_load(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError, match="This old form is refused") as refused:
        migrate_config_doc_on_load(
            {"calibration": {"forward_model": "linear_reservoir"}}, source=source
        )

    assert f"calibration.forward_model dropped: {FORWARD_MODEL_REFUSAL}" in str(refused.value)


def test_pre_release_sealed_run_refused() -> None:
    # The resolved config.toml of example 04 sealed in September holds the export toggles.
    original_bytes = FROZEN_V1.read_bytes()
    doc = tomllib.loads(original_bytes.decode("utf-8"))

    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc(doc)

    assert "export.netcdf" in str(refused.value)
    assert NO_REWRITE in str(refused.value)
    assert FROZEN_V1.read_bytes() == original_bytes


def test_fixing_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fix_config_file(tmp_path / "nope.toml")
