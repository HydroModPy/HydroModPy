"""Tests of the CI removal proof: a fabricated git repository and a scripted ``removal_proof.py``."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import coverage
import pytest
from coverage import CoverageData

from tools.ci import proof
from tools.ci import removal_proof as rp

pytestmark = pytest.mark.allow_subprocess

IMPL = '''"""A module with a branch."""


def classify(x):
    if x < 0:
        return "negative"
    if x == 0:
        return "zero"
    return "positive"


def double(x):
    return 2 * x
'''
OTHER = "def triple(x):\n    return 3 * x\n"
IMPL_TESTS = """from hydromodpy.pkg.impl import classify, double


def test_classify():
    assert classify(-1) == "negative"
    assert classify(0) == "zero"
    assert classify(1) == "positive"


def test_double():
    assert double(2) == 4
"""
IMPL_TESTS_SHORT = IMPL_TESTS.split("\n\n\ndef test_double")[0] + "\n"
OTHER_TESTS = (
    "from hydromodpy.pkg.other import triple\n\n\ndef test_triple():\n    assert triple(2) == 6\n"
)
TOOL_TESTS = "def test_script():\n    assert 1 + 1 == 2\n"
MOVED_TESTS = (
    "from hydromodpy.pkg.impl import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
)
IMPL_FILE = "tests/unit/pkg/test_impl.py"
AGAIN_FILE = "tests/unit/pkg/test_impl_again.py"
OTHER_FILE = "tests/unit/pkg/test_other.py"
TOOL_FILE = "tests/unit/tools/test_script.py"
MOVED_FILE = "tests/unit/pkg/test_moved.py"
LIBRARY_FILE = "hydromodpy/pkg/impl.py"
NOW = datetime.now(UTC)
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


class Repo:
    """A small git repository whose commits are written by a table of files."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.org")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, date: datetime = NOW) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": date.isoformat(),
            "GIT_COMMITTER_DATE": date.isoformat(),
        }
        done = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return done.stdout.strip()

    def commit(self, files: dict[str, str | None], message: str, date: datetime = NOW) -> str:
        for rel, text in files.items():
            target = self.path / rel
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A", date=date)
        self.git("commit", "-q", "--allow-empty", "-m", message, date=date)
        return self.git("rev-parse", "HEAD")


FIRST = {
    "hydromodpy/__init__.py": "",
    "hydromodpy/pkg/__init__.py": "",
    LIBRARY_FILE: IMPL,
    "hydromodpy/pkg/other.py": OTHER,
    "pyproject.toml": "[tool.coverage.run]\nparallel = true\n",
    IMPL_FILE: IMPL_TESTS,
    AGAIN_FILE: IMPL_TESTS,
    OTHER_FILE: OTHER_TESTS,
    TOOL_FILE: TOOL_TESTS,
}


@pytest.fixture()
def repo(tmp_path: Path) -> Repo:
    made = Repo(tmp_path / "clone")
    made.commit(FIRST, "first", LONG_AGO)
    return made


def selected(repo: Path, base: str, head: str, work: Path) -> dict:
    return proof.select(repo, base, head, work)


def check_json(**fields: object) -> dict:
    return {
        "lost_coverage": {},
        "lost_mutants": [],
        "unaccounted_ids": [],
        "baseline_errors": [],
        "restore_files": [],
        "estimated_minutes": 0.0,
    } | fields


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------

AGAIN_IDS = [f"{AGAIN_FILE}::test_classify", f"{AGAIN_FILE}::test_double"]
SELECT_CASES = [
    pytest.param({"tests/unit/pkg/test_new.py": TOOL_TESTS}, "none", [], id="no test removed"),
    pytest.param({OTHER_FILE: OTHER_TESTS + "\n\n"}, "none", [], id="a test file only edited"),
    pytest.param(
        {AGAIN_FILE: None},
        "bounded",
        AGAIN_IDS,
        id="a file whose lines another file runs",
    ),
    pytest.param(
        {IMPL_FILE: IMPL_TESTS_SHORT}, "bounded", [f"{IMPL_FILE}::test_double"], id="one function"
    ),
    pytest.param(
        {IMPL_FILE: IMPL_TESTS_SHORT, MOVED_FILE: MOVED_TESTS},
        "bounded",
        [f"{IMPL_FILE}::test_double"],
        id="a function moved to a new file",
    ),
    pytest.param(
        {AGAIN_FILE: None, LIBRARY_FILE: IMPL + "\n"},
        "changed",
        AGAIN_IDS,
        id="a test and the library change together",
    ),
    pytest.param(
        {TOOL_FILE: None}, "alone", [f"{TOOL_FILE}::test_script"], id="a test of no library module"
    ),
]


@pytest.mark.parametrize(("files", "verdict", "removed"), SELECT_CASES)
def test_the_selection_of_a_change(repo, tmp_path, files, verdict, removed):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit(files, "change")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["format"] == proof.SELECTION_FORMAT
    assert (selection["verdict"], selection["removed"]) == (verdict, removed)
    assert (selection["base"], selection["head"]) == (base, head)
    assert (tmp_path / "work").exists() is (verdict in ("bounded", "alone"))


def test_a_removed_file_is_stood_for_by_the_tests_of_its_module(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit({AGAIN_FILE: None}, "remove the copy")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["files"] == [AGAIN_FILE]
    assert selection["modules"] == [LIBRARY_FILE]
    assert selection["tests_base"] == [IMPL_FILE, AGAIN_FILE]
    assert selection["tests_head"] == [IMPL_FILE]
    assert Path(selection["base_tree"], AGAIN_FILE).is_file()
    assert not Path(selection["head_tree"], AGAIN_FILE).exists()


def test_a_library_change_is_found_without_an_export(repo, tmp_path):
    selection = proved(repo, tmp_path, {AGAIN_FILE: None, LIBRARY_FILE: IMPL + "\n"})
    assert (selection["verdict"], selection["base_tree"], selection["head_tree"]) == (
        "changed",
        None,
        None,
    )
    assert not (tmp_path / "work").exists()


def test_a_moved_function_adds_its_new_file_to_the_tests_after(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit({IMPL_FILE: IMPL_TESTS_SHORT, MOVED_FILE: MOVED_TESTS}, "move")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["tests_head"] == [IMPL_FILE, AGAIN_FILE, MOVED_FILE]
    assert selection["tests_base"] == [IMPL_FILE, AGAIN_FILE]


def test_an_alone_removal_names_the_files_without_a_module(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit({TOOL_FILE: None}, "remove the tool test")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["without_module"] == [TOOL_FILE]
    assert (selection["modules"], selection["tests_base"], selection["tests_head"]) == (
        [],
        [TOOL_FILE],
        [],
    )


def test_a_rename_removes_the_old_functions_and_adds_the_new_file(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    renamed = "tests/unit/tools/test_renamed.py"
    head = repo.commit({TOOL_FILE: None, renamed: TOOL_TESTS}, "rename")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["removed"] == [f"{TOOL_FILE}::test_script"]
    assert (selection["verdict"], selection["tests_head"]) == ("bounded", [renamed])


def test_a_test_file_that_does_not_parse_is_listed_and_left_out(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit(
        {"tests/unit/pkg/test_broken.py": "def test_(:\n", AGAIN_FILE: None}, "break"
    )
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["skipped"] == ["tests/unit/pkg/test_broken.py"]
    assert selection["tests_head"] == [IMPL_FILE]


def test_the_base_may_be_any_older_commit(repo, tmp_path):
    base = repo.git("rev-parse", "HEAD")
    repo.commit({OTHER_FILE: OTHER_TESTS + "\n"}, "edit")
    head = repo.commit({AGAIN_FILE: None}, "remove")
    selection = selected(repo.path, base, head, tmp_path / "work")
    assert selection["removed"] == AGAIN_IDS


def test_select_writes_the_selection_and_exits_0(repo, tmp_path, capsys):
    base = repo.git("rev-parse", "HEAD")
    repo.commit({AGAIN_FILE: None}, "remove")
    argv = ["select", "--repo", str(repo.path), "--base", base, "--work", str(tmp_path / "w")]
    assert proof.main([*argv, "--out", str(tmp_path / "selection.json")]) == 0
    written = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert written["verdict"] == "bounded"
    assert capsys.readouterr().out == (
        "select: 2 test functions gone in 1 files, 1 modules, 2 tests before and 1 after (bounded)\n"
    )


# ---------------------------------------------------------------------------
# prove, with a scripted removal_proof.py
# ---------------------------------------------------------------------------


class ScriptedTool:
    """Stands for ``removal_proof.py``: records each call and answers from a table."""

    def __init__(self, monkeypatch, codes=None, check=None, lines=None, folder_checks=None):
        self.calls: list[list[str]] = []
        self.codes = {"measure": 0, "check": 0} | (codes or {})
        self.check = check
        self.lines = lines or {}
        self.folder_checks = folder_checks or {}
        monkeypatch.setattr(proof, "run_tool", self)

    def __call__(self, command):
        self.calls.append(list(command))
        action = command[2]
        if action == "check":
            out = Path(command[command.index("--out") + 1])
            folder = Path(command[command.index("--after") + 1]).parent.name
            code, check = self.folder_checks.get(folder, (self.codes["check"], self.check))
            budget = float(command[command.index("--budget-minutes") + 1])
            if check is not None and check.get("needs", 0) > budget:
                return 2, rp.PHRASES["budget"].format(n=check["needs"], m=budget)
            if check is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(check), encoding="utf-8")
            return code, self.lines.get("check", "")
        return self.codes["measure"], self.lines.get("measure", "")

    def actions(self) -> list[str]:
        return [call[2] for call in self.calls]


OPTIONS = {
    "scope": "module",
    "budget_minutes": 45.0,
    "mutmut": "mutpy",
    "processes": 4,
    "workers": 2,
    "runner": "fresh",
    "ignore": [],
}


def proved(repo, tmp_path, files):
    base = repo.git("rev-parse", "HEAD")
    head = repo.commit(files, "change")
    return selected(repo.path, base, head, tmp_path / "work")


def test_a_change_that_removes_no_test_runs_nothing(repo, tmp_path, monkeypatch):
    tool = ScriptedTool(monkeypatch)
    selection = proved(repo, tmp_path, {"tests/unit/pkg/test_new.py": TOOL_TESTS})
    code, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert (code, tool.calls, report["verdict"], report["losses"]) == (0, [], "none", [])


def test_both_sides_are_measured_on_their_own_tests_then_checked(repo, tmp_path, monkeypatch):
    tool = ScriptedTool(monkeypatch, check=check_json(estimated_minutes=3.5))
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    work = tmp_path / "work"
    code, report = proof.prove_selection(selection, work, OPTIONS)
    assert (code, tool.actions()) == (0, ["measure", "measure", "check"])
    base_call, head_call, check_call = tool.calls
    assert base_call[3:] == [
        *("--tree", selection["base_tree"], "--out", str(work / "measure-base")),
        *("--workers", "2", "--tests", IMPL_FILE, AGAIN_FILE),
    ]
    assert head_call[head_call.index("--tests") + 1 :] == [IMPL_FILE]
    assert check_call[3:] == [
        *("--before", selection["base_tree"], "--after", selection["head_tree"]),
        *("--measure-before", str(work / "measure-base")),
        *("--measure-after", str(work / "measure-head")),
        *("--mutmut", "mutpy", "--work", str(work / "check"), "--out", str(work / "check.json")),
        *("--scope", "module", "--budget-minutes", "45.0", "--processes", "4"),
        *("--runner", "fresh"),
    ]
    assert report["check"]["estimated_minutes"] == 3.5
    assert (report["removed"], report["tests_base"], report["tests_head"]) == (2, 2, 1)


def test_ignored_paths_go_to_both_measures(repo, tmp_path, monkeypatch):
    tool = ScriptedTool(monkeypatch, check=check_json())
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    options = OPTIONS | {"ignore": ["tests/unit/catchment/test_whitebox.py"]}
    proof.prove_selection(selection, tmp_path / "work", options)
    for call in tool.calls[:2]:
        assert call[-2:] == ["--ignore", "tests/unit/catchment/test_whitebox.py"]


def test_a_loss_gives_exit_1_and_names_each_item(repo, tmp_path, monkeypatch):
    check = check_json(
        lost_coverage={
            LIBRARY_FILE: {
                "lines_count": 2,
                "arcs_count": 1,
                "covered_by": [f"{AGAIN_FILE}::test_double"],
            }
        },
        lost_mutants=[
            {
                "name": "hydromodpy.pkg.impl.x_double__mutmut_1",
                "function": "double",
                "status": "lost",
                "killer": f"{AGAIN_FILE}::test_double",
            }
        ],
        restore_files=[AGAIN_FILE],
    )
    ScriptedTool(monkeypatch, codes={"check": 1}, check=check)
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    code, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert code == 1
    assert report["losses"] == [
        f"lost coverage: {LIBRARY_FILE}, 2 lines and 1 branches, run by {AGAIN_FILE}::test_double",
        "lost mutant: hydromodpy.pkg.impl.x_double__mutmut_1 in double, lost, "
        f"killed before by {AGAIN_FILE}::test_double",
        f"put back: {AGAIN_FILE}",
    ]


@pytest.mark.parametrize("failing", ["measure", "check"])
def test_a_refusal_of_the_tool_is_passed_on_with_its_sentence(repo, tmp_path, monkeypatch, failing):
    phrase = rp.PHRASES["failing"].format(tree="T")
    ScriptedTool(monkeypatch, codes={failing: 2}, lines={failing: phrase}, check=check_json())
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    code, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert (code, report["refusal"]) == (2, phrase)


def test_a_failing_measure_stops_before_the_check(repo, tmp_path, monkeypatch):
    tool = ScriptedTool(monkeypatch, codes={"measure": 2})
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert tool.actions() == ["measure"]


def test_a_change_that_edits_the_library_is_refused_without_a_run(repo, tmp_path, monkeypatch):
    tool = ScriptedTool(monkeypatch)
    selection = proved(repo, tmp_path, {AGAIN_FILE: None, LIBRARY_FILE: IMPL + "\n"})
    code, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert (code, tool.calls) == (2, [])
    assert report["refusal"] == (
        "hydromodpy/ differs between the two trees: "
        "prove a test removal on unchanged code, in a change of its own."
    )


def cover(folder: Path, tree: Path, contexts: dict[str, list[tuple[int, int]]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = CoverageData(basename=str(folder / ".coverage"))
    for context, arcs in contexts.items():
        data.set_context(context)
        data.add_arcs({str(tree / LIBRARY_FILE): arcs, str(tree / TOOL_FILE): [(-1, 1)]})
    data.write()
    (folder / "junit.xml").write_text("<testsuites><testsuite/></testsuites>", encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"tree": str(tree.resolve())}), encoding="utf-8")


IMPL_GONE = {IMPL_FILE: None, AGAIN_FILE: None}


@pytest.mark.parametrize(
    ("contexts", "gone", "code", "lost"),
    [
        pytest.param(
            {f"{TOOL_FILE}::test_script|run": []},
            {},
            0,
            [],
            id="the removed tests run no library line",
        ),
        pytest.param(
            {f"{TOOL_FILE}::test_script|run": [(-1, 4), (4, 5)]},
            IMPL_GONE,
            1,
            [
                f"lost coverage: {LIBRARY_FILE}, 2 lines and 2 branches, run by {TOOL_FILE}::test_script",
                f"put back: {IMPL_FILE}, {AGAIN_FILE}, {TOOL_FILE}",
            ],
            id="the removed tests run library lines that no test left imports",
        ),
    ],
)
def test_a_removal_with_no_test_left_must_run_no_library_line(
    repo, tmp_path, monkeypatch, contexts, gone, code, lost
):
    selection = proved(repo, tmp_path, {TOOL_FILE: None, **gone})
    assert selection["verdict"] == "alone"
    folder = tmp_path / "work" / "measure-removed"

    def measure(command):
        cover(folder, Path(selection["base_tree"]), contexts)
        return 0, ""

    monkeypatch.setattr(proof, "run_tool", measure)
    got, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert (got, report["losses"]) == (code, lost)


def test_an_alone_removal_is_checked_against_the_importers_of_what_it_ran(
    repo, tmp_path, monkeypatch
):
    selection = proved(repo, tmp_path, {TOOL_FILE: None})
    assert selection["verdict"] == "alone"
    work = tmp_path / "work"
    tool = ScriptedTool(monkeypatch, check=check_json())
    scripted = proof.run_tool

    def measure(command):
        if command[command.index("--out") + 1] == str(work / "measure-removed"):
            cover(
                work / "measure-removed",
                Path(selection["base_tree"]),
                {f"{TOOL_FILE}::test_script|run": [(-1, 4), (4, 5)]},
            )
        return scripted(command)

    monkeypatch.setattr(proof, "run_tool", measure)
    code, report = proof.prove_selection(selection, work, OPTIONS)
    assert (code, tool.actions()) == (0, ["measure", "measure", "measure", "check"])
    removed_call, base_call, head_call, _ = tool.calls
    assert removed_call[removed_call.index("--tests") + 1 :] == [TOOL_FILE]
    assert base_call[base_call.index("--tests") + 1 :] == [IMPL_FILE, AGAIN_FILE, TOOL_FILE]
    assert head_call[head_call.index("--tests") + 1 :] == [IMPL_FILE, AGAIN_FILE]
    assert report["check"]["bound"] == [LIBRARY_FILE]


OTHER_LIBRARY = "hydromodpy/pkg/other.py"
OUTSIDE = {
    OTHER_LIBRARY: {"lines_count": 3, "arcs_count": 1, "covered_by": [f"{AGAIN_FILE}::test_double"]}
}


@pytest.mark.parametrize(
    ("scope", "code", "losses", "restore"),
    [
        pytest.param(
            "module",
            0,
            [f"outside the bound, not counted: {OTHER_LIBRARY}, 3 lines and 1 branches"],
            [],
            id="a loss outside the modules of the removed tests is listed, not counted",
        ),
        pytest.param(
            "package",
            1,
            [
                f"lost coverage: {OTHER_LIBRARY}, 3 lines and 1 branches, run by {AGAIN_FILE}::test_double",
                f"put back: {AGAIN_FILE}",
            ],
            [AGAIN_FILE],
            id="the package scope counts a loss in the package of the removed tests",
        ),
    ],
)
def test_a_coverage_loss_counts_only_inside_the_bound(
    repo, tmp_path, monkeypatch, scope, code, losses, restore
):
    check = check_json(lost_coverage=OUTSIDE, restore_files=[AGAIN_FILE])
    ScriptedTool(monkeypatch, codes={"check": 1}, check=check)
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    assert selection["modules"] == [LIBRARY_FILE]
    got, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS | {"scope": scope})
    assert (got, report["losses"], report["check"]["restore_files"]) == (code, losses, restore)
    assert list(report["check"].get("outside_bound", {})) == ([] if code else [OTHER_LIBRARY])


def test_a_loss_inside_the_bound_still_fails_beside_one_outside(repo, tmp_path, monkeypatch):
    inside = {
        LIBRARY_FILE: {
            "lines_count": 1,
            "arcs_count": 0,
            "covered_by": [f"{AGAIN_FILE}::test_classify"],
        }
    }
    check = check_json(lost_coverage=inside | OUTSIDE, restore_files=[AGAIN_FILE])
    ScriptedTool(monkeypatch, codes={"check": 1}, check=check)
    selection = proved(repo, tmp_path, {AGAIN_FILE: None})
    code, report = proof.prove_selection(selection, tmp_path / "work", OPTIONS)
    assert code == 1
    assert report["losses"] == [
        f"lost coverage: {LIBRARY_FILE}, 1 lines and 0 branches, run by {AGAIN_FILE}::test_classify",
        f"put back: {AGAIN_FILE}",
        f"outside the bound, not counted: {OTHER_LIBRARY}, 3 lines and 1 branches",
    ]


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def run_main(capsys, *argv: str) -> tuple[int, str]:
    code = proof.main(list(argv))
    return code, capsys.readouterr().err.strip()


def test_every_refusal_has_its_sentence(repo, tmp_path, capsys, monkeypatch):
    work, out = str(tmp_path / "w"), str(tmp_path / "o.json")
    selection = tmp_path / "selection.json"
    not_selection = tmp_path / "plain.json"
    not_selection.write_text('{"format": "other"}', encoding="utf-8")
    bad_verdict = tmp_path / "verdict.json"
    bad_verdict.write_text(json.dumps({"format": proof.SELECTION_FORMAT, "verdict": "x"}), "utf-8")
    missing_trees = tmp_path / "trees.json"
    missing = {
        "format": proof.SELECTION_FORMAT,
        "verdict": "bounded",
        "base": "a",
        "head": "b",
        "removed": [],
        "files": [],
        "modules": [],
        "tests_base": [],
        "tests_head": [],
        "base_tree": str(tmp_path / "no-base"),
        "head_tree": str(tmp_path / "no-head"),
    }
    missing_trees.write_text(json.dumps(missing), encoding="utf-8")
    monkeypatch.setattr(proof, "run_tool", lambda command: (0, ""))
    selection.write_text("not json", encoding="utf-8")
    where = ["--repo", str(repo.path), "--work", work, "--out", out]
    unknown = "0" * 40
    rows = [
        (
            ["select", *where, "--base", unknown],
            f"{unknown} is not a commit of this clone: "
            "fetch the history of the base (fetch-depth: 0) and give a commit that exists.",
        ),
        (
            ["select", *where, "--base", ""],
            "an empty revision is not a commit of this clone: "
            "fetch the history of the base (fetch-depth: 0) and give a commit that exists.",
        ),
        (
            ["select", *where, "--base", "HEAD", "--head", "nope"],
            "nope is not a commit of this clone: "
            "fetch the history of the base (fetch-depth: 0) and give a commit that exists.",
        ),
        *(
            (
                ["prove", str(path), "--work", work, "--out", out],
                f"{path} is not a selection written by `proof.py select`: run select first.",
            )
            for path in (selection, not_selection, bad_verdict, tmp_path / "absent.json")
        ),
        (
            ["range", *where, "--base", unknown],
            f"{unknown} is not a commit of this clone: "
            "fetch the history of the base (fetch-depth: 0) and give a commit that exists.",
        ),
        (
            ["prove", str(missing_trees), "--work", work, "--out", out],
            f"{tmp_path / 'no-base'} is not there: run `proof.py select` with the same --work first.",
        ),
    ]
    for argv, sentence in rows:
        assert run_main(capsys, *argv) == (2, sentence), argv


def test_a_git_failure_is_refused_with_the_command_and_its_message(repo):
    with pytest.raises(proof.Refusal, match=r"^git cat-file blob nope:none failed: .+"):
        proof.git(repo.path, "cat-file", "blob", "nope:none")


def test_a_library_change_is_refused_by_prove_with_exit_2(repo, tmp_path, capsys):
    base = repo.git("rev-parse", "HEAD")
    repo.commit({AGAIN_FILE: None, LIBRARY_FILE: IMPL + "\n"}, "both")
    picked = ["select", "--repo", str(repo.path), "--base", base]
    work = ["--work", str(tmp_path / "w")]
    assert proof.main([*picked, *work, "--out", str(tmp_path / "s.json")]) == 0
    capsys.readouterr()
    code, err = run_main(
        capsys, "prove", str(tmp_path / "s.json"), *work, "--out", str(tmp_path / "r.json")
    )
    assert (code, err) == (2, rp.PHRASES["differs"])
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["exit_code"] == 2


def test_the_loss_lines_of_a_check_result_are_exact():
    check = check_json(
        lost_coverage={"hydromodpy/a.py": {"lines_count": 1, "arcs_count": 0}},
        unaccounted_ids=["tests/unit/test_x.py::test_y"],
        baseline_errors=["hydromodpy/b.py"],
    )
    assert proof.describe_losses(check) == [
        "lost coverage: hydromodpy/a.py, 1 lines and 0 branches, run by the removed tests",
        "unaccounted test: tests/unit/test_x.py::test_y",
        "module not proved, its tests fail with no mutant: hydromodpy/b.py",
    ]
    assert proof.has_loss(check_json(baseline_errors=["hydromodpy/b.py"]))
    assert not proof.has_loss(check_json())


def test_the_budget_phrase_is_recognised(monkeypatch):
    assert proof.is_budget_refusal(rp.PHRASES["budget"].format(n=9, m=3))
    assert not proof.is_budget_refusal(rp.PHRASES["failing"].format(tree="T"))
    assert not proof.is_budget_refusal(None)


# ---------------------------------------------------------------------------
# week
# ---------------------------------------------------------------------------


def test_the_week_proves_each_removing_commit_against_its_parent(repo, tmp_path, monkeypatch):
    third, fourth = "tests/unit/pkg/test_third.py", "tests/unit/pkg/test_fourth.py"
    repo.commit(
        {third: IMPL_TESTS, fourth: IMPL_TESTS, "tests/unit/pkg/test_old.py": TOOL_TESTS},
        "add",
        LONG_AGO,
    )
    repo.commit({"tests/unit/pkg/test_old.py": None}, "old removal", LONG_AGO)
    edit = repo.commit({OTHER_FILE: OTHER_TESTS + "\n"}, "edit a test", NOW - timedelta(days=5))
    removing = repo.commit({third: None}, "remove the third copy", NOW - timedelta(days=4))
    changed = repo.commit(
        {OTHER_FILE: None, "hydromodpy/pkg/other.py": OTHER + "\n"}, "both", NOW - timedelta(days=3)
    )
    left = repo.commit({IMPL_FILE: IMPL_TESTS_SHORT}, "remove a function", NOW - timedelta(days=2))
    lost = repo.commit({fourth: None}, "remove the fourth copy", NOW - timedelta(days=1))
    big = check_json(estimated_minutes=200.0, needs=250.0)
    ScriptedTool(
        monkeypatch,
        folder_checks={
            removing[:12]: (0, check_json(estimated_minutes=200.0)),
            left[:12]: (0, big),
            lost[:12]: (1, check_json(lost_coverage={LIBRARY_FILE: {"lines_count": 1}})),
        },
    )
    code, report = proof.week(
        repo.path,
        "7 days ago",
        "HEAD",
        tmp_path / "work",
        OPTIONS | {"budget_minutes": 300.0, "scope": "package"},
    )
    names = {
        key: [e["commit"] for e in report[key]]
        for key in ("proved", "lost", "changed", "left", "refused")
    }
    assert names == {
        "proved": [removing],
        "lost": [lost],
        "changed": [changed],
        "left": [left],
        "refused": [],
    }
    assert (code, report["commits"], report["spent_minutes"]) == (1, 5, 200.0)
    assert report["format"] == proof.WEEK_FORMAT
    assert edit not in names["proved"]
    assert report["left"][0]["refusal"].startswith("the mutant proof needs 250.0 minutes")
    assert report["lost"][0]["losses"][0].startswith("lost coverage: hydromodpy/pkg/impl.py")


def test_the_week_trims_each_commit_folder_to_its_json(repo, tmp_path, monkeypatch):
    removing = repo.commit({AGAIN_FILE: None}, "remove the copy", NOW - timedelta(days=1))
    ScriptedTool(monkeypatch, check=check_json())
    code, _ = proof.week(repo.path, "7 days ago", "HEAD", tmp_path / "work", OPTIONS)
    folder = tmp_path / "work" / removing[:12]
    assert code == 0
    assert sorted(p.name for p in folder.iterdir()) == ["check.json", "report.json"]


def test_a_week_without_removal_is_proved_and_empty(repo, tmp_path, monkeypatch):
    repo.commit({OTHER_FILE: OTHER_TESTS + "\n"}, "edit a test", NOW - timedelta(days=1))
    tool = ScriptedTool(monkeypatch)
    code, report = proof.week(repo.path, "7 days ago", "HEAD", tmp_path / "work", OPTIONS)
    assert (code, report["commits"], tool.calls) == (0, 1, [])
    assert not (tmp_path / "work").exists() or not list((tmp_path / "work").iterdir())


def test_a_refusal_in_the_week_fails_it_with_code_2(repo, tmp_path, monkeypatch):
    repo.commit({AGAIN_FILE: None}, "remove the copy", NOW - timedelta(days=1))
    phrase = rp.PHRASES["failing"].format(tree="T")
    ScriptedTool(monkeypatch, codes={"measure": 2}, lines={"measure": phrase})
    code, report = proof.week(repo.path, "7 days ago", "HEAD", tmp_path / "work", OPTIONS)
    assert (code, report["refused"][0]["refusal"]) == (2, phrase)


def test_week_writes_its_report_through_the_command_line(repo, tmp_path, monkeypatch, capsys):
    repo.commit({AGAIN_FILE: None}, "remove the copy", NOW - timedelta(days=1))
    ScriptedTool(monkeypatch, check=check_json())
    out = tmp_path / "week.json"
    argv = ["week", "--repo", str(repo.path), "--work", str(tmp_path / "w"), "--out", str(out)]
    assert proof.main(argv) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert (report["scope"] if "scope" in report else "package", len(report["proved"])) == (
        "package",
        1,
    )
    assert capsys.readouterr().out.startswith("week: 1 commits, 1 proved, 0 lost, 0 changed")


def test_the_week_proves_in_package_scope_by_default():
    assert proof.build_parser().parse_args(["week", "--work", "w", "--out", "o"]).scope == "package"
    assert (
        proof.build_parser().parse_args(["week", "--work", "w", "--out", "o"]).budget_minutes
        == 300.0
    )
    assert (
        proof.build_parser().parse_args(["prove", "s", "--work", "w", "--out", "o"]).budget_minutes
        == 45.0
    )


# ---------------------------------------------------------------------------
# range, the commits of a push
# ---------------------------------------------------------------------------


def test_a_push_that_removes_tests_and_edits_the_library_apart_is_proved(
    repo, tmp_path, monkeypatch
):
    base = repo.git("rev-parse", "HEAD")
    repo.commit({LIBRARY_FILE: IMPL + "\n"}, "edit the library")
    removing = repo.commit({AGAIN_FILE: None}, "remove the copy")
    assert selected(repo.path, base, removing, tmp_path / "whole")["verdict"] == "changed"
    ScriptedTool(monkeypatch, check=check_json())
    code, report = proof.push_range(repo.path, base, "HEAD", tmp_path / "work", OPTIONS)
    assert (code, report["format"], report["commits"]) == (0, proof.RANGE_FORMAT, 2)
    assert [e["commit"] for e in report["proved"]] == [removing]
    assert (report["base"], report["head"]) == (base, removing)


def test_a_commit_of_a_push_that_does_both_is_refused_with_exit_2(repo, tmp_path, monkeypatch):
    base = repo.git("rev-parse", "HEAD")
    removing = repo.commit({AGAIN_FILE: None}, "remove the copy")
    both = repo.commit({OTHER_FILE: None, OTHER_LIBRARY: OTHER + "\n"}, "both")
    ScriptedTool(monkeypatch, check=check_json())
    code, report = proof.push_range(repo.path, base, both, tmp_path / "work", OPTIONS)
    assert code == 2
    assert [e["commit"] for e in report["proved"]] == [removing]
    assert report["changed"] == [
        {"commit": both, "subject": "both", "files": [OTHER_FILE], "refusal": rp.PHRASES["differs"]}
    ]


def test_range_writes_its_report_and_names_each_refusal(repo, tmp_path, monkeypatch, capsys):
    base = repo.git("rev-parse", "HEAD")
    both = repo.commit({OTHER_FILE: None, OTHER_LIBRARY: OTHER + "\n"}, "both")
    ScriptedTool(monkeypatch, check=check_json())
    out = tmp_path / "range.json"
    argv = ["range", "--repo", str(repo.path), "--base", base, "--work", str(tmp_path / "w")]
    assert proof.main([*argv, "--out", str(out)]) == 2
    printed = capsys.readouterr()
    assert printed.out.startswith("range: 1 commits, 0 proved, 0 lost, 1 changed")
    assert printed.err.strip() == f"{both[:12]} {rp.PHRASES['differs']}"
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == proof.RANGE_FORMAT


def test_range_proves_in_module_scope_within_the_job_budget():
    args = proof.build_parser().parse_args(["range", "--base", "b", "--work", "w", "--out", "o"])
    assert (args.scope, args.budget_minutes, args.head) == ("module", 45.0, "HEAD")


# ---------------------------------------------------------------------------
# the real removal_proof.py
# ---------------------------------------------------------------------------

MUTMUT_PYTHON = Path(os.environ.get("HMP_MUTMUT_PYTHON") or "/nonexistent/mutmut-python")
COVERAGE_NEW_ENOUGH = tuple(int(x) for x in coverage.__version__.split(".")[:2]) >= (7, 10)


@pytest.mark.slow
@pytest.mark.skipif(
    not (MUTMUT_PYTHON.is_file() and COVERAGE_NEW_ENOUGH),
    reason="needs mutmut 3.8.0 in HMP_MUTMUT_PYTHON (unset skips) and coverage 7.10",
)
@pytest.mark.parametrize(
    ("files", "code"),
    [
        pytest.param({AGAIN_FILE: None}, 0, id="a copy of a test leaves"),
        pytest.param({IMPL_FILE: None, AGAIN_FILE: None}, 1, id="every test of a module leaves"),
    ],
)
def test_the_real_check_on_a_fabricated_repository(repo, tmp_path, files, code):
    base = repo.git("rev-parse", "HEAD")
    repo.commit(files, "remove")
    work = ["--work", str(tmp_path / "w")]
    out = ["--out", str(tmp_path / "selection.json")]
    assert proof.main(["select", "--repo", str(repo.path), "--base", base, *work, *out]) == 0
    prove = [
        "prove",
        str(tmp_path / "selection.json"),
        *work,
        "--out",
        str(tmp_path / "report.json"),
    ]
    prove += ["--mutmut", str(MUTMUT_PYTHON), "--processes", "2", "--workers", "1"]
    assert proof.main(prove) == code
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["exit_code"] == code
    assert bool(report["losses"]) is (code == 1)
