"""The migration of a configuration reads the rows of the register of changes.

Each shape of a row is played on a live file in its delay (it warns), past its delay
(it is refused with the new name), a sealed run (it reads in silence), the doctor (it
rewrites) and a dotted path. The rows are those of a register written for the case,
passed as an argument. The mechanism of the doctor and of the loader plays on a row
the shipped register carries, ``[modflow6]`` to ``[solver.modflow6]``.
"""

from __future__ import annotations

import tomllib
import warnings
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.config.config_migration import (
    apply_edition,
    fix_config_chain,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_merged_doc,
    migrate_sealed_config_doc,
    rewrite_dotted_path,
)
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    warn_old_form,
)
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.version import __version__
from hydromodpy.schema.changes import migrations_of, outlived, read
from tools.surface_snapshot import toml_fields


def _write(tmp_path: Path, body: str, name: str = "project.toml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _chain(tmp_path: Path, parent: str, child: str) -> tuple[Path, Path]:
    """Write a parent and a child that inherits it; return both paths."""
    first = _write(tmp_path, parent, "parent.toml")
    second = _write(tmp_path, f'base_config = "parent.toml"\n{child}', "child.toml")
    return first, second


def _steps(path: str) -> list[str]:
    """Split a form path into keys: ``{*}`` is the free name ``x``, ``[*]`` a list index."""
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
    """Whether *doc* still holds a value at *path*."""
    try:
        _dig(doc, path)
    except (KeyError, IndexError, TypeError):
        return False
    return True


# --- each shape of a row, on a register written for the case -----------------

HEAD = 'schema = "hydromodpy.changes.v1"\n'
ROWS = HEAD + (
    '[[migration]]\ndocument = "config"\nold = "old_table"\nnew = "new.table"\nsince = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nold = "items[*].type"\nnew = "items[*].kind"\n'
    'since = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nkey = "section.kind"\nold_value = "a"\nnew_value = "b"\n'
    'since = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nold = "late_table"\nnew = "late.table"\nsince = "1.0.0"\n'
    '[[migration]]\ndocument = "config"\nold = "section.gone"\ninstead = "Nothing replaces it."\n'
    'sealed = "drop"\nsince = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nold = "section.left"\n'
    'instead = "Write section.right instead."\nsince = "2.1.0"\n'
)
FIXTURE = read(ROWS)

SHAPES = {
    "a table that moves": ("[old_table]\nx = 1\n", "new.table.x", 1, "old_table -> [new.table]"),
    "a key renamed in each table of a list": (
        '[[items]]\ntype = "flow"\n',
        "items[*].kind",
        "flow",
        "items[0].type -> kind",
    ),
    "a value renamed": ('[section]\nkind = "a"\n', "section.kind", "b", "section.kind: 'a' -> 'b'"),
}


@pytest.mark.parametrize(("text", "path", "value", "told"), SHAPES.values(), ids=SHAPES.keys())
def test_the_doctor_rewrites_each_shape(
    text: str, path: str, value: object, told: str, tmp_path: Path
) -> None:
    file = _write(tmp_path, text)

    assert fix_config_chain(file, register=FIXTURE)[file.resolve()] == [told]
    assert _dig(tomllib.loads(file.read_text(encoding="utf-8")), path) == value
    assert fix_config_chain(file, register=FIXTURE)[file.resolve()] == []


def test_a_form_past_its_delay_is_refused_with_its_new_name(tmp_path: Path) -> None:
    assert outlived("1.0.0", __version__)
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(
            tomllib.loads("[late_table]\nx = 1\n"), source=source, register=FIXTURE
        )

    assert str(refused.value) == (
        f"{source}: late_table -> [late.table]. This old form is refused; "
        f"`hmp doctor --fix-config {source}` rewrites the file."
    )


RETIRED = {
    "a key that left, sealed drop": (
        "[section]\ngone = 1\nkept = 2\n",
        "section.gone",
        {"section": {"kept": 2}},
    ),
    "a key that left with nothing to drop": (
        "[section]\nleft = 1\n",
        "section.left",
        None,
    ),
}


@pytest.mark.parametrize(("text", "label", "sealed"), RETIRED.values(), ids=RETIRED.keys())
def test_a_sealed_run_drops_a_key_that_left_only_when_the_row_says_so(
    text: str, label: str, sealed: object
) -> None:
    doc = tomllib.loads(text)
    if sealed is None:
        with pytest.raises(ConfigValidationError, match=f"a sealed run config holds {label}"):
            migrate_sealed_config_doc(doc, register=FIXTURE)
        return

    assert migrate_sealed_config_doc(doc, register=FIXTURE) == [f"{label} dropped (sealed)"]
    assert doc == sealed


@pytest.mark.parametrize(("text", "label", "sealed"), RETIRED.values(), ids=RETIRED.keys())
def test_the_doctor_leaves_a_key_that_left_and_says_what_to_write(
    text: str, label: str, sealed: object, tmp_path: Path
) -> None:
    del sealed
    file = _write(tmp_path, text)

    changes = fix_config_chain(file, register=FIXTURE)[file.resolve()]

    assert file.read_text() == text
    assert len(changes) == 1 and changes[0].startswith(f"{label}{CANNOT_REWRITE}")


DOTTED = {
    "a phase override": (
        {"calibration": {"phases": [{"name": "p", "overrides": {"old_table.x": 1}}]}},
        ("calibration", "phases", 0, "overrides"),
        {"new.table.x": 1},
    ),
    "a phase override written as tables": (
        {"calibration": {"phases": [{"name": "p", "overrides": {"old_table": {"x": 1}}}]}},
        ("calibration", "phases", 0, "overrides"),
        {"new.table": {"x": 1}},
    ),
    "a bind line": (
        {"sites": {"bind": {"old_table.x": "column"}}},
        ("sites", "bind"),
        {"new.table.x": "column"},
    ),
    "a recipe": (
        {"sites": {"recipes": {"r": {"set": {"old_table.x": 1}}}}},
        ("sites", "recipes", "r", "set"),
        {"new.table.x": 1},
    ),
    "a calibration parameter": (
        {"calibration": {"parameters": {"k": {"path": "old_table.x"}}}},
        ("calibration", "parameters", "k"),
        {"path": "new.table.x"},
    ),
}


@pytest.mark.parametrize(("doc", "where", "after"), DOTTED.values(), ids=DOTTED.keys())
def test_a_dotted_path_follows_the_table_it_names(doc: dict, where: tuple, after: dict) -> None:
    migrate_config_doc(doc, register=FIXTURE)

    node: object = doc
    for step in where:
        node = node[step]  # type: ignore[index]
    assert node == after
    assert rewrite_dotted_path("old_table.x", register=FIXTURE) == "new.table.x"


def test_a_dotted_key_given_twice_is_left_with_the_reason() -> None:
    bind = {"old_table.x": "a", "new.table.x": "b"}

    changes = migrate_config_doc({"sites": {"bind": bind}}, register=FIXTURE)

    assert bind == {"old_table.x": "a", "new.table.x": "b"}
    assert changes == [
        f'sites.bind."old_table.x"{CANNOT_REWRITE}"new.table.x" is given too, keep one'
    ]


def test_a_key_written_under_both_names_keeps_the_new_one_and_says_what_differed() -> None:
    doc = {"old_table": {"x": 1}, "new": {"table": {"x": 2}}}

    changes = migrate_config_doc(doc, register=FIXTURE)

    assert doc == {"new": {"table": {"x": 2}}}
    assert changes == [
        "old_table dropped ([new.table] already set; it held other values: x = 1 against 2)"
    ]


def test_a_directive_of_a_moved_table_and_a_list_a_child_adds_move_too() -> None:
    doc = {"old_table__delete": True, "items__append": [{"type": "flow"}]}

    changes = migrate_config_doc(doc, register=FIXTURE)

    assert doc == {"new": {"table__delete": True}, "items__append": [{"kind": "flow"}]}
    assert "old_table__delete -> new.table__delete" in changes


# --- the editions -------------------------------------------------------------

EDITIONS = read(
    HEAD
    + '[[default]]\nid = "d"\nsince = "2.1.0"\nedition = "2.1"\nkey = "solver.x"\nold = 0.5\n'
    + 'new = 0.45\nquantities = ["metrics"]\ntext = "t"\n'
    + '[[default]]\nid = "e"\nsince = "2.1.0"\nedition = "2.1"\nkey = "flow.bc.{*}.y"\n'
    + 'old = 1\nnew = 2\nquantities = ["metrics"]\ntext = "t"\n'
)

APPLIED = {
    "an older edition, the key not written": (
        {"flow": {"bc": {"r": {}}}},
        "2.0",
        {"flow": {"bc": {"r": {"y": 1}}}, "solver": {"x": 0.5}},
        ["solver.x", "flow.bc.r.y"],
    ),
    "an older edition, the key written": (
        {"solver": {"x": 0.7}},
        "2.0",
        {"solver": {"x": 0.7}},
        [],
    ),
    "the edition of the default": ({}, "2.1", {}, []),
}


@pytest.mark.parametrize(
    ("doc", "edition", "after", "written"), APPLIED.values(), ids=APPLIED.keys()
)
def test_a_file_keeps_the_defaults_of_the_edition_it_writes(
    doc: dict, edition: str, after: dict, written: list[str]
) -> None:
    assert apply_edition(doc, edition=edition, register=EDITIONS) == written
    assert doc == after


def test_an_edition_the_register_does_not_know_is_refused_with_the_ones_it_serves() -> None:
    doc: dict = {"edition": "9.9"}

    with pytest.raises(ConfigValidationError, match="serves 2.0, 2.1") as refused:
        apply_edition(doc, edition="9.9", register=EDITIONS)

    assert doc == {"edition": "9.9"}
    assert [entry["pointer"] for entry in refused.value.details] == ["/edition"]
    with pytest.raises(ConfigValidationError, match="edition names '9.9'"):
        migrate_merged_doc({"edition": "9.9"}, register=EDITIONS)


def test_the_merged_document_and_a_sealed_run_take_the_defaults_of_their_edition() -> None:
    merged: dict = {}
    sealed: dict = {"edition": "2.1"}

    migrate_merged_doc(merged, register=EDITIONS)
    migrate_sealed_config_doc(sealed, register=EDITIONS)

    assert merged == {"solver": {"x": 0.5}}
    assert sealed == {"edition": "2.1"}


# --- the shipped register -----------------------------------------------------


def _keys_of_the_grammar() -> set[str]:
    return {row.split("\t", 1)[0] for row in toml_fields()}


def _a_key_the_models_hold(path: str, keys: set[str]) -> bool:
    return path in keys or any(key.startswith(f"{path}.") for key in keys)


CONFIG_MOVES = [row for row in migrations_of("config") if row.shape == "move"]


@pytest.mark.parametrize(
    "row",
    [row for row in CONFIG_MOVES if row.rule is None],
    ids=lambda row: f"{row.old}->{row.new}",
)
def test_every_move_is_rewritten_by_the_doctor(row, tmp_path: Path) -> None:
    path = _write(tmp_path, tomlkit.dumps(_document_with(str(row.old), "probe-value")))

    fix_config_file(path)

    after = tomllib.loads(path.read_text(encoding="utf-8"))
    assert _dig(after, rewrite_dotted_path(str(row.new), sealed=True)) == "probe-value"
    assert not _holds(after, str(row.old))
    assert fix_config_file(path) == []


def test_the_parent_tables_of_transport_move_after_their_parameters() -> None:
    olds = [row.old for row in CONFIG_MOVES]

    for name in ("modflow6gwt", "modflow6prt"):
        assert olds.index(f"transport.{name}.parameters") < olds.index(f"transport.{name}")


_FROZEN_V1 = Path(__file__).parent / "fixtures" / "frozen_run_config_export_v1.toml"


def test_a_run_sealed_by_a_pre_release_of_example_04_is_refused() -> None:
    """The resolved ``config.toml`` of example 04 sealed in September holds the export toggles."""
    original_bytes = _FROZEN_V1.read_bytes()
    doc = tomllib.loads(original_bytes.decode("utf-8"))

    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc(doc)

    assert "export.netcdf" in str(refused.value)
    assert "This version does not rewrite the file." in str(refused.value)
    assert _FROZEN_V1.read_bytes() == original_bytes


# --- the mechanism of the loader and of the doctor, on a row of a later version ----------

MODFLOW6 = "[modflow6.process_specific]\nvka = 2.0\n"


def test_a_form_the_loader_cannot_rewrite_does_not_promise_the_doctor() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="seed left: why") as told:
        warn_old_form("project.toml", "calibration.seed left: why")
    assert "hmp doctor" not in str(told[0].message)


def test_a_dry_run_writes_nothing_and_gives_the_diff(tmp_path: Path) -> None:
    path = _write(tmp_path, MODFLOW6)
    diffs: dict[Path, str] = {}

    changes = fix_config_chain(path, dry_run=True, diffs=diffs)

    assert changes[path.resolve()] == ["modflow6 -> [solver.modflow6]"]
    assert path.read_text() == MODFLOW6
    assert "+[solver.modflow6.process_specific]" in diffs[path.resolve()]


def test_a_backend_split_across_two_files_is_named_by_the_merge(tmp_path: Path) -> None:
    """``kind = "custom"`` in a parent and ``name`` in a child say the name only together."""
    _, child = _chain(
        tmp_path, '[solver.backend]\nkind = "custom"\n', '[solver.backend]\nname = "plugged"\n'
    )

    with pytest.warns(ConfigKeyRenamedWarning, match="solver.backend.kind -> solver.backend"):
        merged = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert merged["solver"]["backend"] == "plugged"


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fix_config_file(tmp_path / "nope.toml")


# --- the rules of the register and the forms of a pre-release ---------------------------

SOLVER_FORMS = (
    (
        "the MODFLOW 6 table",
        "[modflow6.process_specific]\nvka = 2.0\n",
        "solver.modflow6.process_specific.vka",
        2.0,
    ),
    (
        "the MODFLOW-NWT table",
        "[modflownwt.runtime.upw]\nhdry = -999.0\n",
        "solver.modflow_nwt.runtime.upw.hdry",
        -999.0,
    ),
    (
        "the Boussinesq table",
        '[flow.runtime]\nbackend = "local"\n',
        "solver.boussinesq.backend",
        "local",
    ),
    (
        "a shipped backend",
        '[solver.backend]\nkind = "modflow_nwt"\n',
        "solver.backend",
        "modflow_nwt",
    ),
    (
        "a plugin backend",
        '[solver.backend]\nkind = "custom"\nname = "plugged"\n',
        "solver.backend",
        "plugged",
    ),
    (
        "a transport parameters table",
        "[transport.modflow6gwt.parameters]\nporosity = 0.2\n",
        "transport.modflow6.porosity",
        0.2,
    ),
    (
        "the scaffold of hmp init",
        '[[simulation.process]]\nid = "flow"\ntype = "flow"\n',
        "simulation.process[*].kind",
        "flow",
    ),
)


SOLVER_PATHS = (
    ("modflow6.process_specific.vka", "solver.modflow6.process_specific.vka"),
    ("modflownwt.runtime.nwt.headtol", "solver.modflow_nwt.runtime.nwt.headtol"),
    ("flow.runtime.max_iterations", "solver.boussinesq.max_iterations"),
    ("solver.backend.kind", "solver.backend"),
    ("transport.mt3dms.parameters.porosity", "transport.mt3dms.porosity"),
)


@pytest.mark.parametrize(("old", "new"), SOLVER_PATHS)
def test_a_dotted_path_of_a_form_of_2_0_moves_with_it(old: str, new: str) -> None:
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


def test_a_plugin_backend_written_as_dotted_keys_becomes_its_name() -> None:
    doc = {
        "sites": {
            "recipes": {
                "r": {"set": {"solver.backend.kind": "custom", "solver.backend.name": "plugged"}}
            }
        }
    }

    migrate_config_doc(doc)

    assert doc["sites"]["recipes"]["r"]["set"] == {"solver.backend": "plugged"}


def test_a_transport_table_beside_its_parameters_is_kept_and_they_are_dropped() -> None:
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


def test_an_empty_parent_table_of_transport_is_dropped_under_its_new_name() -> None:
    doc = {"transport": {"modflow6gwt": {}, "modflow6": {"porosity": 0.2}}}

    changes = migrate_config_doc(doc)

    assert doc == {"transport": {"modflow6": {"porosity": 0.2}}}
    assert changes == [
        "transport.modflow6gwt dropped ([transport.modflow6] already set; it was empty)"
    ]


def test_a_source_kind_of_2_0_is_renamed_in_every_section() -> None:
    doc = {"data": {"dem": {"sources": [{"source": "custom", "path": "inputs/dem.tif"}]}}}

    changes = migrate_config_doc(doc)

    assert doc["data"]["dem"]["sources"][0]["source"] == "file"
    assert changes == ["data.dem.sources[0].source: 'custom' -> 'file'"]


def test_doctor_refusal_of_dem_init_path(tmp_path: Path) -> None:
    from hydromodpy.project.doctor import refusal_of

    path = _write(
        tmp_path, '[geographic.catchment]\nkind = "dem"\ndem_init_path = "inputs/dem.tif"\n'
    )

    refusal = refusal_of(path)

    assert refusal is not None
    assert "dem_init_path was removed in 2.0.0" in str(refusal)
    assert "[[data.dem.sources]]" in str(refusal)
    assert 'source = "file"' in str(refusal)


def test_doctor_writes_the_dem_row_a_load_refuses(tmp_path: Path) -> None:
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


def test_a_sealed_run_reads_the_dem_init_path_as_its_source() -> None:
    doc = {"geographic": {"catchment": {"dem_init_path": "inputs/dem.tif"}}}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        migrate_sealed_config_doc(doc)

    assert doc["data"] == {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}}
    assert "catchment" not in doc["geographic"]


def test_doctor_refusal_of_bare_name(tmp_path: Path) -> None:
    from hydromodpy.project.doctor import refusal_of

    path = _write(
        tmp_path,
        '[geographic.catchment]\nkind = "dem"\n'
        '[[data.dem.sources]]\nsource = "file"\npath = "dem.tif"\n',
    )

    refusal = refusal_of(path)

    assert refusal is not None
    assert "'dem.tif' is a bare name" in str(refusal)
    assert "inputs/dem.tif" in str(refusal)


FORWARD_MODEL_REFUSAL = (
    "a forward model is a solver backend since 2.0.0: name it by solver.backend, register "
    "it in the hydromodpy.solver entry-point group, and calibrate it with the pipeline evaluator"
)


def test_a_live_forward_model_key_is_refused_on_load(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError, match="This old form is refused") as refused:
        migrate_config_doc_on_load(
            {"calibration": {"forward_model": "linear_reservoir"}}, source=source
        )

    assert f"calibration.forward_model dropped: {FORWARD_MODEL_REFUSAL}" in str(refused.value)


def test_a_live_scored_forward_evaluator_is_dropped_and_the_doctor_says_why(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, '[calibration]\nevaluator = "scored_forward_model"\n')

    told = fix_config_file(path)

    assert told == [f"calibration.evaluator dropped: {FORWARD_MODEL_REFUSAL}"]
    assert "evaluator" not in tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert fix_config_file(path) == []


def test_a_sealed_document_holding_the_forward_model_at_null_loses_it_in_silence() -> None:
    doc = {"calibration": {"forward_model": None}}

    migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {}}


def test_a_sealed_document_holding_a_forward_model_name_warns() -> None:
    doc = {"calibration": {"forward_model": "linear_reservoir"}}

    with pytest.warns(ConfigKeyRenamedWarning, match="calibration.forward_model retired"):
        migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {}}


# --- the two cache keys removed in 2.0.0 ---------------------------------------

REMOVED_CACHE_KEYS = (
    ("reuse_existing_outputs", "under .hmp/products/"),
    ("reg_fold", 'state = "conditioned"'),
)


def test_a_root_section_the_caller_names_is_never_created_by_an_edition() -> None:
    doc: dict = {"flow": {"bc": {}}}

    written = apply_edition(doc, edition="2.0", register=EDITIONS, optional_sections={"solver"})

    assert written == ["flow.bc.{*}.y"][:0]
    assert doc == {"flow": {"bc": {}}}
    kept: dict = {"solver": {}}
    assert apply_edition(kept, edition="2.0", register=EDITIONS, optional_sections={"solver"}) == [
        "solver.x"
    ]
