"""Small contracts of the documentation tooling: CI schedule, renamed keys, TOML diff, API pages.

Each test pins a fact that a page states and that the tool reads from the code.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from hydromodpy.schema.changes import read
from tools.docs import legacy_keys, tests_index

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def ext_path():
    """The Sphinx extensions are modules of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    yield
    sys.path.remove(str(EXT))


# ---------------------------------------------------------------- tests_index


def test_petsc4py_is_read_in_the_steps_of_each_job() -> None:
    job = {"steps": [{"run": "conda install petsc petsc4py"}]}
    assert tests_index.installs_petsc4py(job)
    assert not tests_index.installs_petsc4py({"steps": [{"run": "pip install -e .[test]"}]})
    assert not tests_index.installs_petsc4py({})


def test_a_workflow_with_two_jobs_marks_only_the_job_that_installs_petsc4py(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        textwrap.dedent(
            """\
            name: both
            # petsc4py is only named in this comment
            on:
              schedule:
                - cron: "30 5 * * *"
            jobs:
              plain:
                name: Nightly plain run
                steps:
                  - run: python -m pytest tests/validation -m "not petsc"
              conda:
                name: Nightly conda run
                steps:
                  - run: mamba install petsc4py
                  - run: python -m pytest tests/validation -m petsc
            """
        )
    )
    jobs = {j["job"]: j["petsc4py"] for j in tests_index.schedule(tmp_path)}
    assert jobs == {"Nightly plain run": False, "Nightly conda run": True}


# ---------------------------------------------------------------- legacy_keys

MOVES = """schema = "hydromodpy.changes.v1"
[[migration]]
document = "config"
old = "a.old_table"
new = "a.new_table"
since = "3.0.0"
[[migration]]
document = "config"
old = "b.list[*].old_key"
new = "b.list[*].new_key"
since = "2.0.0"
[[migration]]
document = "config"
old = "c.long_gone"
new = "c.gone_for_good"
since = "1.0.0"
[[migration]]
document = "config"
key = "d.kind"
old_value = "a"
new_value = "b"
since = "3.0.0"
[[migration]]
document = "config"
old = "e.left"
instead = "write something else"
since = "3.0.0"
[[migration]]
document = "fields"
old = "f.stored"
new = "f.stored_now"
since = "3.0.0"
"""


def test_a_move_row_inside_its_delay_is_a_key_a_live_file_may_still_write() -> None:
    register = read(MOVES)

    assert legacy_keys.accepted_old_names(register) == {
        "a.old_table": legacy_keys.MIGRATES,
        "b.list.old_key": legacy_keys.MIGRATES,
    }


def test_every_move_row_is_a_move_of_the_page_even_past_its_delay() -> None:
    register = read(MOVES)

    assert legacy_keys.moved_tables(register) == {
        "a.old_table": "a.new_table",
        "b.list.old_key": "b.list.new_key",
        "c.long_gone": "c.gone_for_good",
    }


def test_the_shipped_register_moves_the_solver_tables() -> None:
    accepted = legacy_keys.accepted_old_names()
    moves = legacy_keys.moved_tables()

    assert accepted["modflow6"] == legacy_keys.MIGRATES
    assert moves["modflow6"] == "solver.modflow6"
    assert moves["flow.runtime"] == "solver.boussinesq"
    assert set(accepted) <= set(moves)


def test_a_pre_release_form_is_refused_and_no_row_moves_it() -> None:
    accepted = legacy_keys.accepted_old_names()
    forms = legacy_keys.prerelease_paths()

    assert {"calibration.optimizer_kwargs", "calibration.max_iter"} <= forms
    assert not forms & set(accepted)
    assert "calibration.optimizer_kwargs" not in accepted


def test_a_form_that_refuses_a_value_is_not_a_removed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hydromodpy.config.config_migration import PrereleaseForm

    monkeypatch.setattr(
        legacy_keys,
        "PRERELEASE_FORMS",
        (
            PrereleaseForm("a.old.{*}"),
            PrereleaseForm("b.kind", "robin", has_value=True),
            PrereleaseForm("c.list[*].x"),
        ),
    )

    assert legacy_keys.prerelease_paths() == {"a.old", "c.list.x"}


def test_a_rename_the_loader_does_not_read_is_left_out() -> None:
    assert "flow.never_read_key" not in legacy_keys.accepted_old_names(read(MOVES))


def _block(
    hmp_params, monkeypatch: pytest.MonkeyPatch, *, removed=(), renamed=(), nodes=None
) -> str:
    """Render the changes page for one pair, released version to this tree, and return its HTML."""
    from types import SimpleNamespace

    class Page(hmp_params.ChangelogDirective):
        env = SimpleNamespace(docname="changes")

    pair = {
        "from": "1.0.0",
        "to": hmp_params.CURRENT,
        "renamed": [{"from": old, "to": new} for old, new in renamed],
        "removed": list(removed),
        "added": [],
        "changed": [],
    }
    history = {"versions": ["1.0.0", hmp_params.CURRENT], "pairs": [pair]}
    monkeypatch.setattr(hmp_params, "current_builder", lambda: SimpleNamespace())
    monkeypatch.setattr(hmp_params, "version_history", lambda: history)
    monkeypatch.setitem(hmp_params.S, "nodes", nodes or {})
    monkeypatch.setitem(hmp_params.S, "home", {})
    return Page.__new__(Page).run()[0].astext()


def test_a_moved_key_is_listed_as_still_loading_and_not_breaking(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _block(hmp_params, monkeypatch, removed=["modflow6"])

    assert "A file that writes them still loads, as each line says." in html
    assert "still loads; ConfigKeyRenamedWarning names the new key" in html
    assert "hmp doctor --fix-config rewrites the file" in html
    assert "tc-req" not in html


def test_a_pre_release_key_is_marked_refused_since_2_0_0(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _block(hmp_params, monkeypatch, removed=["calibration.optimizer_kwargs"])

    assert "refused since 2.0.0" in html
    assert "the message names each such key" in html
    assert 'tc-req">breaking' in html


def test_a_removed_key_the_loader_refuses_keeps_the_block_breaking(
    monkeypatch: pytest.MonkeyPatch, ext_path: None
) -> None:
    import hmp_params

    html = _block(hmp_params, monkeypatch, removed=["modflow6", "flow.never_read_key"])

    assert "refused, unless its line says it still loads" in html
    assert 'tc-req">breaking' in html


# ---------------------------------------------------------------- TOML diff


def test_the_diff_of_two_files_is_taken_after_the_base_config_merge(
    tmp_path: Path, ext_path: None
) -> None:
    import hmp_params

    (tmp_path / "base.toml").write_text('[simulation]\nname = "a"\n\n[flow]\nk = 1.0\n')
    (tmp_path / "child.toml").write_text('base_config = "base.toml"\n\n[simulation]\nname = "b"\n')
    diff = hmp_params.resolved_toml_diff(tmp_path / "base.toml", tmp_path / "child.toml")
    lines = diff.splitlines()
    assert lines[:2] == ["--- base", "+++ child"]
    assert '-name = "a"' in lines
    assert '+name = "b"' in lines
    assert not any("k = 1.0" in line and line[0] in "+-" for line in lines)


def test_two_files_that_resolve_alike_give_an_empty_diff(tmp_path: Path, ext_path: None) -> None:
    import hmp_params

    (tmp_path / "a.toml").write_text('[simulation]\nname = "a"\n')
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n')
    assert hmp_params.resolved_toml_diff(tmp_path / "a.toml", tmp_path / "b.toml") == ""


def test_the_staircase_diffs_resolve_on_the_real_files(ext_path: None) -> None:
    import hmp_params

    example = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
    diff = hmp_params.resolved_toml_diff(
        example / "step1_minimal.toml", example / "step2_local_data.toml"
    )
    assert '+name = "nancon_step2_local"' in diff.splitlines()


# ---------------------------------------------------------------- API pages


def test_a_generated_page_that_nothing_produces_any_more_is_pruned(
    tmp_path: Path, ext_path: None
) -> None:
    import hmp_api

    kept = tmp_path / "Run.md"
    gone = tmp_path / "Figure.md"
    mine = tmp_path / "written-by-hand.md"
    for page in (kept, gone):
        page.write_text(f"{hmp_api.HEADER}\n\n# page\n")
    mine.write_text("# a page somebody wrote\n")
    hmp_api.prune_generated({kept}, tmp_path)
    assert kept.exists()
    assert not gone.exists()
    assert mine.exists()


def test_the_type_aliases_of_a_verb_are_spelled_out_once(ext_path: None) -> None:
    import hmp_api

    verb = {
        "returns": [{"name": "Readable", "alias": "np.ndarray | xr.DataArray"}],
        "type_aliases": [
            {"name": "ConfigLike", "alias": "str | os.PathLike[str] | HydroModPyConfig"},
            {"name": "Readable", "alias": "np.ndarray | xr.DataArray"},
        ],
    }
    html = hmp_api.type_aliases_html(verb)
    assert "ConfigLike" in html
    assert "HydroModPyConfig" in html
    assert "Readable" not in html
    assert hmp_api.type_aliases_html({"returns": [], "type_aliases": []}) == ""


# ---------------------------------------------------------------- register page

REGISTER_ROWS = """schema = "hydromodpy.changes.v1"
[[bug]]
id = "a_bug"
since = "3.0.0"
versions = "<3.0.0"
quantities = ["metrics", "heads@modflow6"]
text = "A `bug` in [section] reads *wrong*."
[[default]]
id = "a_default"
since = "3.0.0"
edition = "3.0"
key = "solver.x"
old = 0.5
new = "auto"
quantities = ["metrics"]
text = "A default."
[[recipe]]
id = "a_recipe"
since = "3.0.0"
effect = "refusal"
quantities = []
text = "A recipe."
[[migration]]
document = "config"
old = "a.b"
new = "a.c"
since = "3.0.0"
[[migration]]
document = "config"
old = "a.left"
instead = "Write a.right."
sealed = "drop"
since = "3.0.0"
[[migration]]
document = "config"
key = "d.kind"
old_value = "a"
new_value = "b"
since = "3.0.0"
[[migration]]
document = "sidecar"
old = "s.old"
new = "s.new"
since = "3.0.0"
"""


def _table_text(table: str, register) -> list[list[str]]:
    import hmp_changes_register as page

    head, cells, widths = page.rows_of(table, register)
    assert len(head) == len(widths)
    assert all(len(row) == len(head) for row in cells)
    return cells


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("bug", [["a_bug", "3.0.0", "<3.0.0", "metrics, heads@modflow6"]]),
        ("default", [["a_default", "3.0.0", "3.0", "solver.x", "0.5", '"auto"', "metrics"]]),
        ("recipe", [["a_recipe", "3.0.0", "refusal", "none"]]),
        (
            "migration",
            [
                ["config", "a.b -> a.c", "3.0.0", "3.2.0"],
                ["config", "a.left (left)", "3.0.0", "3.0.0"],
                ["config", 'd.kind: "a" -> "b"', "3.0.0", "3.2.0"],
                ["sidecar", "s.old -> s.new", "3.0.0", "-"],
            ],
        ),
    ],
)
def test_each_row_of_the_register_is_a_row_of_its_table(
    table: str, expected: list[list[str]], ext_path: None
) -> None:
    cells = _table_text(table, read(REGISTER_ROWS))

    # The last column is the text of the row, checked apart from the short columns.
    assert [row[: len(expected[0])] for row in cells] == expected


def test_a_retired_key_says_what_to_write_and_that_a_sealed_run_drops_it(ext_path: None) -> None:
    cells = _table_text("migration", read(REGISTER_ROWS))

    assert cells[1][4] == "Write a.right. A sealed run drops it."
    assert cells[0][4] == "-"


def test_the_text_of_a_row_is_shown_as_it_is_written(ext_path: None) -> None:
    import hmp_changes_register as page

    head, cells, widths = page.rows_of("bug", read(REGISTER_ROWS))
    shown = page.table_node(head, cells, widths, page.CODE_COLUMN["bug"]).astext()

    assert "A `bug` in [section] reads *wrong*." in shown
    assert "a_bug" in shown


def test_the_shipped_register_is_listed_row_for_row(ext_path: None) -> None:
    import hmp_changes_register as page

    from hydromodpy.schema.changes import REGISTER

    for table, rows in (
        ("bug", REGISTER.bugs),
        ("default", REGISTER.defaults),
        ("recipe", REGISTER.recipes),
        ("migration", REGISTER.migrations),
    ):
        _head, cells, _widths = page.rows_of(table, REGISTER)
        assert len(cells) == len(rows)
    assert {row[0] for row in page.rows_of("bug", REGISTER)[1]} == {b.id for b in REGISTER.bugs}


def test_the_directive_takes_a_known_table_only(ext_path: None) -> None:
    from types import SimpleNamespace

    import hmp_changes_register as page
    from docutils.parsers.rst import DirectiveError

    class Page(page.RegisterDirective):
        env = SimpleNamespace(note_dependency=lambda path: None)

    def run(table: str):
        directive = Page.__new__(Page)
        directive.arguments = [table]
        return directive.run()

    assert run("bug")
    with pytest.raises(DirectiveError):
        run("everything")


def test_no_tool_of_the_docs_reads_a_private_name_of_the_migration_module() -> None:
    files = [
        ROOT / "tools" / "surface_snapshot.py",
        ROOT / "tools" / "changes_changelog.py",
        ROOT / "tools" / "docs" / "legacy_keys.py",
        ROOT / "tools" / "docs" / "toml_changelog.py",
        EXT / "hmp_params.py",
        EXT / "hmp_changes_register.py",
    ]
    for path in files:
        assert "config_migration._" not in path.read_text(), path.name
