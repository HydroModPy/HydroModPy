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
from packaging.version import Version

from hydromodpy.config.config_migration import (
    PRERELEASE_FORMS,
    RULES,
    apply_edition,
    document_path,
    edition_of,
    fix_config_chain,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_layers,
    migrate_merged_doc,
    migrate_sealed_config_doc,
    moved_paths,
    rewrite_dotted_path,
)
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    forget_old_forms_told,
    warn_old_form,
)
from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.toml_io.overrides import SET_SOURCE
from hydromodpy.core.version import __version__
from hydromodpy.schema.changes import REGISTER, migrations_of, outlived, read
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
def test_a_live_file_in_the_delay_loads_with_a_warning(
    text: str, path: str, value: object, told: str, tmp_path: Path
) -> None:
    forget_old_forms_told()
    doc = tomllib.loads(text)
    source = tmp_path / "project.toml"

    with pytest.warns(ConfigKeyRenamedWarning) as warned:
        changes = migrate_config_doc_on_load(doc, source=source, register=FIXTURE)

    assert changes == [told]
    assert _dig(doc, path) == value
    assert f"hmp doctor --fix-config {source}" in str(warned[0].message)


@pytest.mark.parametrize(("text", "path", "value", "told"), SHAPES.values(), ids=SHAPES.keys())
def test_a_sealed_run_reads_each_shape_in_silence(
    text: str, path: str, value: object, told: str
) -> None:
    doc = tomllib.loads(text)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert migrate_sealed_config_doc(doc, register=FIXTURE) == [told]

    assert _dig(doc, path) == value


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


def test_a_form_past_its_delay_still_reads_in_a_sealed_run_and_through_the_doctor(
    tmp_path: Path,
) -> None:
    sealed = {"late_table": {"x": 1}}
    migrate_sealed_config_doc(sealed, register=FIXTURE)
    file = _write(tmp_path, "[late_table]\nx = 1\n")
    fix_config_chain(file, register=FIXTURE)

    assert sealed == {"late": {"table": {"x": 1}}}
    assert tomllib.loads(file.read_text()) == {"late": {"table": {"x": 1}}}


def test_a_path_past_its_delay_moves_only_for_a_sealed_document() -> None:
    assert rewrite_dotted_path("late_table.x", register=FIXTURE) == "late_table.x"
    assert rewrite_dotted_path("late_table.x", sealed=True, register=FIXTURE) == "late.table.x"


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
def test_a_live_file_that_holds_a_key_that_left_is_refused_with_what_to_write(
    text: str, label: str, sealed: object, tmp_path: Path
) -> None:
    del sealed
    with pytest.raises(ConfigValidationError, match=label) as refused:
        migrate_config_doc_on_load(
            tomllib.loads(text), source=tmp_path / "project.toml", register=FIXTURE
        )

    assert "it left in 2.1.0" in str(refused.value)


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


def test_set_reads_a_form_in_its_delay_and_does_not_promise_the_doctor() -> None:
    forget_old_forms_told()
    layer = {"old_table": {"x": 1}}

    with pytest.warns(ConfigKeyRenamedWarning, match="write the new name") as warned:
        migrate_layers([(SET_SOURCE, layer)], register=FIXTURE)

    assert layer == {"new": {"table": {"x": 1}}}
    assert "hmp doctor" not in str(warned[0].message)


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


def test_a_file_that_writes_no_edition_is_of_the_first_one() -> None:
    assert edition_of({}) == "2.0"
    assert edition_of({"edition": "2.1"}) == "2.1"


def test_the_merged_document_and_a_sealed_run_take_the_defaults_of_their_edition() -> None:
    merged: dict = {}
    sealed: dict = {"edition": "2.1"}

    migrate_merged_doc(merged, register=EDITIONS)
    migrate_sealed_config_doc(sealed, register=EDITIONS)

    assert merged == {"solver": {"x": 0.5}}
    assert sealed == {"edition": "2.1"}


# --- the shipped register -----------------------------------------------------


def test_every_rule_a_row_names_is_a_function_of_the_table() -> None:
    named = {row.rule for row in migrations_of("config") if row.rule is not None}

    assert named == set(RULES)


def _keys_of_the_grammar() -> set[str]:
    return {row.split("\t", 1)[0] for row in toml_fields()}


def _a_key_the_models_hold(path: str, keys: set[str]) -> bool:
    return path in keys or any(key.startswith(f"{path}.") for key in keys)


CONFIG_MOVES = [row for row in migrations_of("config") if row.shape == "move"]


@pytest.mark.parametrize("row", CONFIG_MOVES, ids=lambda row: f"{row.old}->{row.new}")
def test_every_move_leads_to_a_key_the_models_hold_and_away_from_one(row) -> None:
    keys = _keys_of_the_grammar()

    assert _a_key_the_models_hold(document_path(str(row.new)), keys), f"{row.new} is no key"
    assert document_path(str(row.old)) not in keys, f"{row.old} is still a key"


@pytest.mark.parametrize(
    "row",
    [row for row in migrations_of("config") if row.shape == "value"],
    ids=lambda row: f"{row.key}={row.old_value}",
)
def test_every_renamed_value_is_held_against_its_key(row) -> None:
    steps = str(row.key).replace("[*]", "").split(".")
    assert any(
        len(parts) == len(steps) and all(s in (p, "{*}") for s, p in zip(steps, parts, strict=True))
        for parts in (key.split(".") for key in _keys_of_the_grammar())
    )


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


def test_hmp_init_of_2_0_loads_with_a_warning_until_2_2(tmp_path: Path) -> None:
    """``[[simulation.process]] type`` is the form the scaffold of 2.0.0 wrote."""
    row = next(row for row in CONFIG_MOVES if row.old == "simulation.process[*].type")
    forget_old_forms_told()
    doc = {"simulation": {"process": [{"id": "flow", "type": "flow", "solvers": ["modflow6"]}]}}

    with pytest.warns(ConfigKeyRenamedWarning, match="type -> kind"):
        migrate_config_doc_on_load(doc, source=tmp_path / "run.toml")

    assert doc["simulation"]["process"][0]["kind"] == "flow"
    assert (row.since, outlived(row.since, "2.1.9"), outlived(row.since, "2.2.0")) == (
        "2.0.0",
        False,
        True,
    )


def test_no_old_python_name_or_command_form_outlives_its_delay() -> None:
    from hydromodpy._lazy import OLD_NAMES
    from hydromodpy.cli.conventions import OLD_CLI_FORMS

    late = [
        f"{name} (since {entry.since})"
        for name, entry in OLD_NAMES.items()
        if outlived(entry.since, __version__)
    ]
    late += [
        f"{form.old} (since {form.since})"
        for form in OLD_CLI_FORMS
        if outlived(form.since, __version__)
    ]
    assert late == [], (
        f"HydroModPy {__version__} still holds old names past their delay: {late}. Delete each "
        "one from OLD_NAMES in hydromodpy/_lazy.py or OLD_CLI_FORMS in hydromodpy/cli/conventions.py."
    )


def test_every_row_of_the_config_states_a_version_of_2_or_later() -> None:
    assert all(Version(row.since) >= Version("2.0.0") for row in migrations_of("config"))
    identities = [(row.old, row.key, repr(row.old_value)) for row in REGISTER.migrations]
    assert len(identities) == len(set(identities))


def test_every_rename_a_model_declares_has_its_row_or_its_pre_release_form() -> None:
    """``renamed_from`` names a path a row moves, or a form only a pre-release wrote."""
    from hydromodpy.core.config_kit.base import HydroModelBase

    known = {document_path(str(row.old)) for row in migrations_of("config") if row.old}
    known |= {document_path(form.path) for form in PRERELEASE_FORMS}
    known |= {
        "mesh_catchment",
        "mesh_input",
        "modflow6.sgrid.planar",
        "modflownwt.sgrid.planar",
        "modflow6.sgrid.grid_dual",
        "modflownwt.sgrid.grid_dual",
    }
    declared: set[str] = set()
    todo = [HydroModelBase]
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        if not cls.__module__.startswith("hydromodpy."):
            continue
        for field in cls.model_fields.values():
            extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
            declared.update(extra.get("renamed_from") or ())
    assert declared
    assert sorted(declared - known) == []


_FROZEN_V1 = Path(__file__).parent / "fixtures" / "frozen_run_config_export_v1.toml"


def test_a_run_sealed_by_a_pre_release_of_example_04_is_refused() -> None:
    """The resolved ``config.toml`` of example 04 sealed in September holds the export toggles."""
    original_bytes = _FROZEN_V1.read_bytes()
    doc = tomllib.loads(original_bytes.decode("utf-8"))

    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc(doc)

    assert "export.netcdf" in str(refused.value)
    assert 'pip install "hydromodpy~=2.0.0"' in str(refused.value)
    assert _FROZEN_V1.read_bytes() == original_bytes


# --- the mechanism of the loader and of the doctor, on a row of 2.1.0 ----------

MODFLOW6 = "[modflow6.process_specific]\nvka = 2.0\n"


def test_a_load_migrates_in_memory_and_warns_once_per_key_and_file(tmp_path: Path) -> None:
    forget_old_forms_told()
    source = tmp_path / "project.toml"
    doc = tomllib.loads(MODFLOW6)

    with pytest.warns(ConfigKeyRenamedWarning) as told:
        changes = migrate_config_doc_on_load(doc, source=source)

    assert changes == ["modflow6 -> [solver.modflow6]"]
    assert doc == {"solver": {"modflow6": {"process_specific": {"vka": 2.0}}}}
    assert len(told) == 1
    assert f"hmp doctor --fix-config {source}" in str(told[0].message)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigKeyRenamedWarning)
        assert migrate_config_doc_on_load(tomllib.loads(MODFLOW6), source=source) == changes
    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(MODFLOW6), source=tmp_path / "other.toml")


def test_a_report_on_a_file_sees_its_old_forms_again(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    forget_old_forms_told()
    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(MODFLOW6), source=source)

    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(MODFLOW6), source=source)


def test_a_form_the_loader_cannot_rewrite_does_not_promise_the_doctor() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="seed left: why") as told:
        warn_old_form("project.toml", "calibration.seed left: why")
    assert "hmp doctor" not in str(told[0].message)


def test_a_current_document_is_left_untouched_and_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = tomllib.loads('[simulation]\nname = "cheze"\nif_exists = "version"\n')
    with caplog.at_level("INFO"), warnings.catch_warnings():
        warnings.simplefilter("error")
        changes = migrate_config_doc_on_load(doc, source="cheze.toml")
    assert changes == []
    assert caplog.records == []
    assert migrate_config_doc(tomllib.loads('[[export]]\nvariables = "head"\n')) == []


def test_the_doctor_follows_the_chain_and_rewrites_each_file_that_holds_an_old_form(
    tmp_path: Path,
) -> None:
    parent, child = _chain(
        tmp_path,
        "# the project\n[modflow6.process_specific]\nvka = 2.0 # stiff\n",
        '# one run\n[flow.runtime]\nbackend = "local" # serial\n',
    )

    changes = fix_config_chain(child)

    assert changes == {
        parent: ["modflow6 -> [solver.modflow6]"],
        child: ["flow.runtime -> [solver.boussinesq]"],
    }
    assert "# the project" in parent.read_text()
    assert "# stiff" in parent.read_text()
    assert "# one run" in child.read_text()
    assert "# serial" in child.read_text()
    assert tomllib.loads(parent.read_text())["solver"] == {
        "modflow6": {"process_specific": {"vka": 2.0}}
    }
    assert fix_config_chain(child) == {parent: [], child: []}
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigKeyRenamedWarning)
        load_toml_with_base_config(child, root=ROOT_CONFIG)


def test_a_dry_run_writes_nothing_and_gives_the_diff(tmp_path: Path) -> None:
    path = _write(tmp_path, MODFLOW6)
    diffs: dict[Path, str] = {}

    changes = fix_config_chain(path, dry_run=True, diffs=diffs)

    assert changes[path.resolve()] == ["modflow6 -> [solver.modflow6]"]
    assert path.read_text() == MODFLOW6
    assert "+[solver.modflow6.process_specific]" in diffs[path.resolve()]


def test_a_warning_names_the_file_that_holds_the_key(tmp_path: Path) -> None:
    holder, child = _chain(tmp_path, MODFLOW6, "[workflow]\nprofile = false\n")
    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning) as told:
        load_toml_with_base_config(child, root=ROOT_CONFIG)

    messages = [str(warning.message) for warning in told]
    assert any("modflow6 -> [solver.modflow6]" in message for message in messages)
    for message in messages:
        assert message.startswith(f"{holder}: ")
        assert f"hmp doctor --fix-config {holder}" in message


def test_a_backend_split_across_two_files_is_named_by_the_merge(tmp_path: Path) -> None:
    """``kind = "custom"`` in a parent and ``name`` in a child say the name only together."""
    _, child = _chain(
        tmp_path, '[solver.backend]\nkind = "custom"\n', '[solver.backend]\nname = "plugged"\n'
    )
    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning, match="solver.backend.kind -> solver.backend"):
        merged = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert merged["solver"]["backend"] == "plugged"


def test_the_doctor_follows_a_directive_and_a_list_a_child_adds(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "modflow6__delete = true\n\n[[simulation.process__append]]\n"
        'id = "late"\ntype = "flow"\nsolvers = ["modflow6"]\n',
    )

    fix_config_file(path)

    assert tomllib.loads(path.read_text()) == {
        "solver": {"modflow6__delete": True},
        "simulation": {
            "process__append": [{"id": "late", "kind": "flow", "solvers": ["modflow6"]}]
        },
    }


def test_the_doctor_reads_a_file_that_carries_a_byte_order_mark(tmp_path: Path) -> None:
    """tomlkit reads a BOM as an empty key, which used to abort the whole fix."""
    path = tmp_path / "project.toml"
    path.write_text("﻿" + MODFLOW6, encoding="utf-8")

    assert fix_config_file(path) == ["modflow6 -> [solver.modflow6]"]
    assert tomllib.loads(path.read_text()) == {
        "solver": {"modflow6": {"process_specific": {"vka": 2.0}}}
    }


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fix_config_file(tmp_path / "nope.toml")


def test_the_doctor_leaves_a_current_file_as_it_is(tmp_path: Path) -> None:
    text = '[simulation]\nname = "x"\n'
    path = _write(tmp_path, text)

    assert fix_config_file(path) == []
    assert path.read_text() == text


def test_a_moved_table_loads_through_the_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[workflow]\nmode = "simulation"\n[geographic]\nsource_mode = "synthetic"\n' + MODFLOW6,
    )
    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning):
        config = HydroModPyConfig.from_toml(path)

    assert held_tables_of(config.solver)["modflow6"].process_specific.vka == 2.0


# --- the rules of the register and the forms of 2.0.0 ---------------------------

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


@pytest.mark.parametrize(
    ("case", "text", "path", "value"), SOLVER_FORMS, ids=[row[0] for row in SOLVER_FORMS]
)
def test_a_form_of_2_0_loads_with_a_warning(
    case: str, text: str, path: str, value: object, tmp_path: Path
) -> None:
    del case
    forget_old_forms_told()
    doc = tomllib.loads(text)

    with pytest.warns(ConfigKeyRenamedWarning, match="hmp doctor --fix-config"):
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml")

    assert _dig(doc, path) == value


@pytest.mark.parametrize(
    ("case", "text", "path", "value"), SOLVER_FORMS, ids=[row[0] for row in SOLVER_FORMS]
)
def test_a_sealed_document_reads_a_form_of_2_0_in_silence(
    case: str, text: str, path: str, value: object
) -> None:
    del case
    doc = tomllib.loads(text)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        migrate_sealed_config_doc(doc)

    assert _dig(doc, path) == value


@pytest.mark.parametrize(
    ("case", "text", "path", "value"), SOLVER_FORMS, ids=[row[0] for row in SOLVER_FORMS]
)
def test_the_doctor_rewrites_a_form_of_2_0(
    case: str, text: str, path: str, value: object, tmp_path: Path
) -> None:
    del case
    file = _write(tmp_path, text)

    assert fix_config_file(file)

    assert _dig(tomllib.loads(file.read_text(encoding="utf-8")), path) == value
    assert fix_config_file(file) == []


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


def test_a_path_of_the_backend_name_leads_to_the_backend() -> None:
    assert rewrite_dotted_path("solver.backend.name") == "solver.backend"
    assert {row.row.old for row in moved_paths()} >= {"modflow6", "solver.backend.kind"}


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


def test_a_backend_table_with_another_key_is_left_for_the_loader_to_refuse() -> None:
    doc = {"solver": {"backend": {"kind": "modflow6", "extra": 1}}}

    migrate_config_doc(doc)

    assert doc["solver"]["backend"] == {"kind": "modflow6", "extra": 1}


def test_a_transport_table_loses_its_parameters_level() -> None:
    doc = tomllib.loads(
        "[transport.mt3dms.parameters]\nporosity = 0.1\n"
        "[transport.modflow6gwt.parameters]\nporosity = 0.2\n"
        "[transport.modflow6prt.parameters]\nstop_time = 5\n"
    )

    changes = migrate_config_doc(doc)

    assert doc["transport"] == {
        "mt3dms": {"porosity": 0.1},
        "modflow6": {"porosity": 0.2},
        "modflow6_prt": {"stop_time": 5},
    }
    assert "transport.modflow6gwt.parameters -> [transport.modflow6]" in changes


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
    from hydromodpy.cli.commands.doctor import _refusal_of

    path = _write(
        tmp_path, '[geographic.catchment]\nkind = "dem"\ndem_init_path = "inputs/dem.tif"\n'
    )

    refusal = _refusal_of(path)

    assert refusal is not None
    assert "dem_init_path was removed in 2.1.0" in str(refusal)
    assert "[[data.dem.sources]]" in str(refusal)
    assert 'source = "file"' in str(refusal)


def test_doctor_writes_the_dem_row_a_load_refuses(tmp_path: Path) -> None:
    path = _write(
        tmp_path, '[geographic.catchment]\nkind = "dem"\ndem_init_path = "inputs/dem.tif"\n'
    )

    told = fix_config_file(path)

    assert told == [
        "geographic.catchment.dem_init_path -> [[data.dem.sources]] path 'inputs/dem.tif' "
        "(dem_init_path was removed in 2.1.0: declare the DEM as [[data.dem.sources]] "
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
    from hydromodpy.cli.commands.doctor import _refusal_of

    path = _write(
        tmp_path,
        '[geographic.catchment]\nkind = "dem"\n'
        '[[data.dem.sources]]\nsource = "file"\npath = "dem.tif"\n',
    )

    refusal = _refusal_of(path)

    assert refusal is not None
    assert "'dem.tif' is a bare name" in str(refusal)
    assert "inputs/dem.tif" in str(refusal)


FORWARD_MODEL_REFUSAL = (
    "a forward model is a solver backend since 2.1.0: name it by solver.backend, register "
    "it in the hydromodpy.solver entry-point group, and calibrate it with the pipeline evaluator"
)


def test_a_live_forward_model_key_is_refused_on_load(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError, match="This old form is refused") as refused:
        migrate_config_doc_on_load(
            {"calibration": {"forward_model": "linear_reservoir"}}, source=source
        )

    assert f"calibration.forward_model dropped: {FORWARD_MODEL_REFUSAL}" in str(refused.value)


def test_a_live_forward_model_key_is_dropped_and_the_doctor_says_why(tmp_path: Path) -> None:
    """The doctor has nothing to write in its place, so it drops the key and says why."""
    path = _write(tmp_path, '[calibration]\nforward_model = "linear_reservoir"\nmethod = "grid"\n')

    told = fix_config_file(path)

    assert told == [f"calibration.forward_model dropped: {FORWARD_MODEL_REFUSAL}"]
    calib = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert "forward_model" not in calib
    assert calib["method"] == "grid"
    assert fix_config_file(path) == []


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

    # A document of no edition keeps the default of 2.0: no series per trial.
    assert doc == {"calibration": {"persist_trial_series": False}}


def test_a_sealed_document_holding_a_forward_model_name_warns() -> None:
    doc = {"calibration": {"forward_model": "linear_reservoir"}}

    with pytest.warns(ConfigKeyRenamedWarning, match="calibration.forward_model retired"):
        migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {"persist_trial_series": False}}


# --- the two cache keys removed in 2.1.0 ---------------------------------------

REMOVED_CACHE_KEYS = (
    ("reuse_existing_outputs", "under .hmp/products/"),
    ("reg_fold", 'state = "conditioned"'),
)


@pytest.mark.parametrize(("key", "fragment"), REMOVED_CACHE_KEYS)
def test_a_live_file_holding_a_removed_cache_key_is_refused_with_what_replaces_it(
    key: str, fragment: str, tmp_path: Path
) -> None:
    doc = {"geographic": {key: False}}

    with pytest.raises(ConfigValidationError, match="it left in 2.1.0") as refused:
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml")

    assert f"geographic.{key}" in str(refused.value)
    assert fragment in str(refused.value)


@pytest.mark.parametrize(("key", "fragment"), REMOVED_CACHE_KEYS)
def test_a_sealed_run_drops_a_removed_cache_key_in_silence(key: str, fragment: str) -> None:
    """The resolved configs of ``frozen_runs`` replay without drift: the key leaves in silence."""
    del fragment
    doc = {"geographic": {key: False, "dem_resolution": 25.0}}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        changes = migrate_sealed_config_doc(doc)

    assert changes == [f"geographic.{key} dropped (sealed)"]
    assert doc == {"geographic": {"dem_resolution": 25.0}}


def test_a_root_section_the_caller_names_is_never_created_by_an_edition() -> None:
    doc: dict = {"flow": {"bc": {}}}

    written = apply_edition(doc, edition="2.0", register=EDITIONS, optional_sections={"solver"})

    assert written == ["flow.bc.{*}.y"][:0]
    assert doc == {"flow": {"bc": {}}}
    kept: dict = {"solver": {}}
    assert apply_edition(kept, edition="2.0", register=EDITIONS, optional_sections={"solver"}) == [
        "solver.x"
    ]
