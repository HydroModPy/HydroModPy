"""Tests of the removal proof: tables over fabricated coverage data and a scripted mutant runner."""

from __future__ import annotations

import contextlib
import json
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from coverage import CoverageData

from tools.ci import removal_proof as rp

IMPL = "class Thing:\n    def run(self):\n        return 1\n\n\ndef helper():\n    return 2\n"
ARCS = [(-1, 1), (1, 2), (2, 3), (3, -2)]
MUTANT = "hydromodpy.pkg.impl.xǁThingǁrun__mutmut_1"
TEST_ONE = "tests/unit/pkg/test_a.py::test_one"
TEST_TWO = "tests/unit/pkg/test_b.py::test_two"
BODY = (
    "def test_{n}():\n    from hydromodpy.pkg.impl import Thing\n\n    assert Thing().run() == 1\n"
)
LONG_TWO = BODY.format(n="two") + "    assert True\n"


def write(tree: Path, rel: str, text: str = "") -> Path:
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_tree(root: Path, name: str = "tree", tests: dict[str, str] | None = None) -> Path:
    tree = root / name
    write(tree, "hydromodpy/__init__.py", "from hydromodpy.pkg.impl import Thing\n")
    write(tree, "hydromodpy/pkg/__init__.py", "from .impl import Thing\n")
    write(tree, "hydromodpy/pkg/impl.py", IMPL)
    write(tree, "hydromodpy/pkg/other.py", "VALUE = 3\n\n\ndef twice():\n    return 6\n")
    write(tree, "pyproject.toml", "[tool.coverage.run]\nparallel = true\n")
    for rel, text in (tests or {}).items():
        write(tree, rel, text)
    return tree


def make_cov(folder: Path, tree: Path, contexts: dict[str, dict[str, list]], lines=False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    data = CoverageData(basename=str(folder / ".coverage"))
    for context, files in contexts.items():
        data.set_context(context)
        payload = {str(tree / rel): items for rel, items in files.items()}
        (data.add_lines if lines else data.add_arcs)(payload)
    data.write()
    return folder / ".coverage"


def junit(rows: list[tuple[str, str, str]]) -> str:
    cases = []
    for classname, name, status in rows:
        inner = {
            "passed": "",
            "skipped": '<skipped type="pytest.skip" message="s"/>',
            "xfail": '<skipped type="pytest.xfail" message="x"/>',
            "failed": '<failure message="f"/>',
        }[status]
        cases.append(
            f'<testcase classname="{classname}" name="{name}" time="0.5">{inner}</testcase>'
        )
    return f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>"


def make_measure(folder: Path, tree: Path, contexts, rows, lines=False) -> Path:
    make_cov(folder, tree, contexts, lines)
    (folder / "junit.xml").write_text(junit(rows), encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"tree": str(tree.resolve())}), encoding="utf-8")
    return folder


def ctx(test: str, phase: str = "run") -> str:
    return f"{test}|{phase}"


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

CANDIDATE_FILE = BODY.format(n="x")
CANDIDATE_ROWS = [
    ("passes and runs the library", CANDIDATE_FILE, "passed", True, set(), "pool"),
    ("skipped case", CANDIDATE_FILE, "skipped", True, set(), "not_green"),
    ("xfail case", CANDIDATE_FILE, "xfail", True, set(), "not_green"),
    ("red case", CANDIDATE_FILE, "failed", True, set(), "not_green"),
    (
        "allow_subprocess mark",
        "# allow_subprocess\n" + CANDIDATE_FILE,
        "passed",
        True,
        set(),
        "allow_subprocess",
    ),
    (
        "text subprocess",
        "import subprocess\n" + CANDIDATE_FILE,
        "passed",
        True,
        set(),
        "subprocess",
    ),
    (
        "text sys.executable",
        "import sys\nsys.executable\n" + CANDIDATE_FILE,
        "passed",
        True,
        set(),
        "subprocess",
    ),
    ("file in KEEP", CANDIDATE_FILE, "passed", True, {"tests/unit/pkg/test_a.py"}, "keep"),
    ("folder in KEEP", CANDIDATE_FILE, "passed", True, {"tests/unit"}, "keep"),
    (
        "imports the repo, runs no library line",
        CANDIDATE_FILE,
        "passed",
        False,
        set(),
        "no_coverage",
    ),
    (
        "imports nothing, runs no library line",
        "def test_x():\n    assert 1 + 1 == 2\n",
        "passed",
        False,
        set(),
        "unconditional",
    ),
    (
        "imports nothing but reads a file of the tree",
        "def test_x():\n    assert open('pyproject.toml').read()\n",
        "passed",
        False,
        set(),
        "no_coverage",
    ),
]


@pytest.mark.parametrize(
    ("source", "status", "covered", "keep", "expected"),
    [row[1:] for row in CANDIDATE_ROWS],
    ids=[row[0] for row in CANDIDATE_ROWS],
)
def test_candidates_by_reason(tmp_path, source, status, covered, keep, expected):
    tree = make_tree(tmp_path, tests={"tests/unit/pkg/test_a.py": source})
    contexts = {ctx(TEST_ONE): {"hydromodpy/pkg/impl.py": ARCS}} if covered else {"": {}}
    rows = [("tests.unit.pkg.test_a", "test_x", status)]
    cov = rp.load_coverage(make_cov(tmp_path / "m", tree, contexts), tree)
    index = rp.build_index(tree)
    files = rp.scan_files(tree, ["tests/unit/pkg/test_a.py"], index)
    cases = rp.parse_junit(junit(rows), tree)
    covered_id = "tests/unit/pkg/test_a.py::test_x"
    if covered:
        cov.items = {covered_id: cov.items.pop(TEST_ONE)}
    pool, unconditional, skipped = rp.pick_candidates(
        list(files.values()), rp.group_cases(cases), cov, keep
    )
    found = {
        "pool": bool(pool),
        "unconditional": bool(unconditional),
        **{reason: covered_id in ids for reason, ids in skipped.items()},
    }
    assert found.get(expected) is True
    assert sum(found.values()) == 1


def test_a_function_that_did_not_run_is_kept(tmp_path):
    tree = make_tree(tmp_path, tests={"tests/unit/pkg/test_a.py": CANDIDATE_FILE})
    files = rp.scan_files(tree, ["tests/unit/pkg/test_a.py"], rp.build_index(tree))
    cov = rp.Coverage(arcs=True)
    _, _, skipped = rp.pick_candidates(list(files.values()), {}, cov, set())
    assert skipped["not_run"] == ["tests/unit/pkg/test_a.py::test_x"]


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [(["passed", "passed", "passed"], "pool"), (["passed", "failed", "passed"], "not_green")],
    ids=["all cases green", "one case red"],
)
def test_parametrized_cases_are_grouped_by_function(tmp_path, statuses, expected):
    source = "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2, 3])\ndef test_x(n):\n    from hydromodpy.pkg.impl import Thing\n"
    tree = make_tree(tmp_path, tests={"tests/unit/pkg/test_a.py": source})
    rows = [("tests.unit.pkg.test_a", f"test_x[{n}]", s) for n, s in enumerate(statuses)]
    cases = rp.parse_junit(junit(rows), tree)
    fid = "tests/unit/pkg/test_a.py::test_x"
    cov = rp.Coverage(arcs=True, items={fid: {"hydromodpy/pkg/impl.py": {1}}})
    files = rp.scan_files(tree, ["tests/unit/pkg/test_a.py"], rp.build_index(tree))
    pool, _, skipped = rp.pick_candidates(list(files.values()), rp.group_cases(cases), cov, set())
    assert (len(pool) == 1) == (expected == "pool")
    assert skipped.get("not_green", []) == ([] if expected == "pool" else [fid])


def test_junit_classes_and_worst_status(tmp_path):
    source = "class TestK:\n    def test_m(self):\n        pass\n"
    tree = make_tree(tmp_path, tests={"tests/unit/pkg/test_a.py": source})
    text = junit(
        [
            ("tests.unit.pkg.test_a.TestK", "test_m[a]", "passed"),
            ("tests.unit.pkg.test_a.TestK", "test_m[b]", "xfail"),
        ]
    )
    cases = rp.parse_junit(text, tree)
    assert set(cases) == {
        "tests/unit/pkg/test_a.py::TestK::test_m[a]",
        "tests/unit/pkg/test_a.py::TestK::test_m[b]",
    }
    assert {c.status for c in cases.values()} == {"passed", "xfail"}


# ---------------------------------------------------------------------------
# Greedy cover
# ---------------------------------------------------------------------------


def fn(fid: str, lines: int = 5) -> rp.ScannedFunction:
    return rp.ScannedFunction(fid, fid.split("::")[0], 1, lines)


IMPL_PATH = "hydromodpy/pkg/impl.py"


def cover(items: dict[str, list], block: list | None = None, arcs=True) -> rp.Coverage:
    pack = (lambda xs: {rp.pack_arc(a, b) for a, b in xs}) if arcs else set
    cov = rp.Coverage(arcs=arcs)
    cov.items = {f: {IMPL_PATH: pack(xs)} for f, xs in items.items()}
    cov.block = {IMPL_PATH: pack(block)} if block else {}
    return cov


GREEDY_ROWS = [
    (
        "a line only one function runs keeps that function",
        {"a": [(1, 2), (2, 3)], "b": [(1, 2)]},
        None,
        ["a", "b"],
        ["b"],
    ),
    (
        "an arc only one function runs stays",
        {"a": [(1, 2), (2, 3), (3, 4), (2, 4)], "b": [(1, 2), (2, 3), (3, 4)]},
        None,
        ["a", "b"],
        ["b"],
    ),
    ("a line also run at import leaves", {"a": [(1, 2)]}, [(1, 2)], ["a"], ["a"]),
    (
        "two duplicates, one leaves",
        {"a": [(1, 2), (2, 3)], "b": [(1, 2), (2, 3)]},
        None,
        ["a", "b"],
        ["a"],
    ),
    ("a test with no item is not removed", {"a": []}, None, ["a"], []),
]


@pytest.mark.parametrize(
    ("items", "block", "order", "expected"),
    [row[1:] for row in GREEDY_ROWS],
    ids=[row[0] for row in GREEDY_ROWS],
)
def test_greedy_cover(items, block, order, expected):
    removed = rp.greedy_cover(cover(items, block), [fn(f) for f in order])
    assert sorted(removed) == sorted(expected)


def test_greedy_cover_on_line_data_without_branches():
    cov = cover({"a": [1, 2], "b": [1, 2, 3]}, arcs=False)
    assert sorted(rp.greedy_cover(cov, [fn("a"), fn("b")])) == ["a"]


def test_the_setup_context_belongs_to_the_test(tmp_path):
    tree = make_tree(tmp_path)
    contexts = {
        ctx(TEST_ONE, "setup"): {IMPL_PATH: [(1, 2)]},
        ctx(TEST_ONE): {IMPL_PATH: [(2, 3)]},
        ctx(TEST_ONE, "teardown"): {IMPL_PATH: [(3, 4)]},
        ctx(TEST_TWO + "[p]"): {IMPL_PATH: [(1, 2), (2, 3), (3, 4)]},
        "": {IMPL_PATH: [(5, 6)]},
    }
    cov = rp.load_coverage(make_cov(tmp_path / "m", tree, contexts), tree)
    assert set(cov.items) == {TEST_ONE, TEST_TWO}
    assert cov.items[TEST_ONE][IMPL_PATH] == {rp.pack_arc(*a) for a in [(1, 2), (2, 3), (3, 4)]}
    assert cov.block[IMPL_PATH] == {rp.pack_arc(5, 6)}
    assert sorted(rp.greedy_cover(cov, [fn(TEST_ONE)])) == [TEST_ONE]


def test_greedy_takes_the_longest_candidate_first():
    cov = cover({"short": [(1, 2)], "long": [(1, 2)], "other": [(1, 2)]})
    removed = rp.greedy_cover(cov, [fn("short", 3), fn("long", 30), fn("other", 8)])
    assert sorted(removed) == ["long", "other"]


def test_line_data_files_load_without_arcs(tmp_path):
    tree = make_tree(tmp_path)
    data = make_cov(tmp_path / "m", tree, {ctx(TEST_ONE): {IMPL_PATH: [1, 2, 9]}}, lines=True)
    cov = rp.load_coverage(data, tree)
    assert not cov.arcs
    assert cov.items[TEST_ONE][IMPL_PATH] == {1, 2, 9}


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------

SUBJECT_ROWS = [
    (
        "a name re-exported by a package",
        "from hydromodpy.pkg import Thing\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/pkg/impl.py"},
    ),
    (
        "a name defined in its module",
        "from hydromodpy.pkg.other import VALUE\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/pkg/other.py"},
    ),
    (
        "a submodule imported by name",
        "from hydromodpy.pkg import other\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/pkg/other.py"},
    ),
    (
        "a dotted import",
        "import hydromodpy.pkg.impl\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/pkg/impl.py"},
    ),
    (
        "the facade alone for import hydromodpy",
        "import hydromodpy\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/__init__.py"},
    ),
    (
        "a name of the facade resolves to its definition",
        "from hydromodpy import Thing\n",
        "tests/unit/pkg/test_a.py",
        {"hydromodpy/pkg/impl.py"},
    ),
    (
        "the module the file name says",
        "x = 1\n",
        "tests/unit/pkg/test_other.py",
        {"hydromodpy/pkg/other.py"},
    ),
    ("a file name that matches nothing", "x = 1\n", "tests/unit/pkg/test_nothing.py", set()),
    ("a name outside the library", "from numpy import array\n", "tests/unit/pkg/test_a.py", set()),
]


@pytest.mark.parametrize(
    ("source", "path", "expected"), [r[1:] for r in SUBJECT_ROWS], ids=[r[0] for r in SUBJECT_ROWS]
)
def test_subjects_of_a_test_file(tmp_path, source, path, expected):
    tree = make_tree(tmp_path, tests={path: source})
    files = rp.scan_files(tree, [path], rp.build_index(tree))
    assert files[path].subjects == expected


def test_a_test_file_name_prefers_the_module_of_its_folder(tmp_path):
    tree = make_tree(tmp_path, tests={"tests/unit/pkg/test_twice.py": "x = 1\n"})
    write(tree, "hydromodpy/zone/twice.py", "def twice():\n    return 2\n")
    write(tree, "hydromodpy/pkg/twice.py", "def twice():\n    return 4\n")
    files = rp.scan_files(tree, ["tests/unit/pkg/test_twice.py"], rp.build_index(tree))
    assert files["tests/unit/pkg/test_twice.py"].subjects == {"hydromodpy/pkg/twice.py"}


# ---------------------------------------------------------------------------
# Names of mutants
# ---------------------------------------------------------------------------

NAME_ROWS = [
    (
        "a function",
        "hydromodpy.pkg.impl.x_helper__mutmut_4",
        ("hydromodpy.pkg.impl", None, "helper"),
    ),
    (
        "a private function",
        "hydromodpy.pkg.impl.x__name_of__mutmut_12",
        ("hydromodpy.pkg.impl", None, "_name_of"),
    ),
    ("a method", MUTANT, ("hydromodpy.pkg.impl", "Thing", "run")),
    (
        "a dunder method",
        "hydromodpy.pkg.impl.xǁThingǁ__init____mutmut_2",
        ("hydromodpy.pkg.impl", "Thing", "__init__"),
    ),
]


@pytest.mark.parametrize(
    ("name", "expected"), [r[1:] for r in NAME_ROWS], ids=[r[0] for r in NAME_ROWS]
)
def test_mutant_names(name, expected):
    assert rp.parse_mutant(name) == expected


def test_the_line_range_of_a_mutated_function_comes_from_the_source(tmp_path):
    tree = make_tree(tmp_path)
    spans = rp.function_spans(tree, IMPL_PATH)
    assert spans[("Thing", "run")] == (3, 3)
    assert spans[(None, "helper")] == (7, 7)
    assert rp.module_file(tree, "hydromodpy.pkg") == "hydromodpy/pkg/__init__.py"
    assert rp.module_file(tree, "hydromodpy.pkg.impl") == IMPL_PATH


@pytest.mark.parametrize(
    "name", ["plain_name", "hydromodpy.pkg.impl.helper", "mod.y_helper__mutmut_1"]
)
def test_an_unknown_mutant_name_is_refused(name):
    with pytest.raises(rp.Refusal, match="is not a mutmut 3.8 mutant name"):
        rp.parse_mutant(name)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_modules_are_taken_by_gain_over_cost():
    gain = {"a": 100.0, "b": 10.0, "c": 50.0}
    seconds = {"a": 10.0, "b": 100.0, "c": 25.0}
    assert rp.rank_modules(gain, seconds) == ["a", "c", "b"]
    assert rp.take_modules(gain, seconds, 40.0) == ["a", "c"]
    assert rp.take_modules(gain, seconds, 5.0) == []


def test_a_module_with_no_mutant_costs_nothing():
    assert rp.take_modules({"a": 5.0, "b": 9.0}, {"a": 0.0, "b": 10.0}, 0.0) == ["a"]


def test_a_removed_function_shares_its_lines_between_its_subjects():
    removed = {"f": fn("f", 10), "g": fn("g", 4)}
    gain = rp.module_gain(removed, {"f": frozenset({"x", "y"}), "g": frozenset({"x"})})
    assert gain == {"x": 9.0, "y": 5.0}


@pytest.mark.parametrize(
    ("total", "target", "processes", "expected"),
    [(1000, 600, 1, 3.0), (1000, 600, 2, 1.5), (500, 600, 1, 0.0), (1000, 100, 1, None)],
    ids=["two modules", "two processes", "already under target", "never reached"],
)
def test_hours_to_target(total, target, processes, expected):
    gain, seconds = {"a": 300.0, "b": 200.0}, {"a": 3600.0, "b": 7200.0}
    assert rp.hours_to_target(gain, seconds, total, target, processes) == expected


FOLD_FILE = (
    "def test_a():\n    assert f(1) == 2\n\n\ndef test_b():\n    assert f(3) == 4\n\n\n"
    "def test_c():\n    assert g(1)\n\n\nclass TestK:\n    def test_a(self):\n        assert f(5) == 6\n"
)


def test_functions_that_differ_by_literals_only_are_a_fold_group(tmp_path):
    path = "tests/unit/pkg/test_f.py"
    tree = make_tree(tmp_path, tests={path: FOLD_FILE})
    files = rp.scan_files(tree, [path], rp.build_index(tree))
    groups = rp.fold_groups(list(files.values()), lambda fid, file: True)
    assert groups == [{"file": path, "ids": [f"{path}::test_a", f"{path}::test_b"]}]
    only_b = rp.fold_groups(list(files.values()), lambda fid, file: fid.endswith("test_b"))
    assert only_b == []


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        ("tests/unit/pkg/test_a.py", "from hydromodpy.pkg.other import VALUE\n", "test_other.py"),
        ("tests/unit/pkg/test_other.py", "from hydromodpy.pkg.other import VALUE\n", None),
        (
            "tests/unit/pkg/test_a.py",
            "import hydromodpy.pkg.other\nimport hydromodpy.pkg.impl\n",
            None,
        ),
    ],
    ids=["one subject elsewhere", "already in its file", "two subjects"],
)
def test_a_function_moves_to_the_file_named_for_its_one_module(tmp_path, path, source, expected):
    tree = make_tree(tmp_path, tests={path: source + "\n\ndef test_x():\n    pass\n"})
    files = rp.scan_files(tree, [path], rp.build_index(tree))
    moves = rp.move_targets(list(files.values()), lambda fid, file: True)
    assert [m["to"] for m in moves] == ([f"tests/unit/pkg/{expected}"] if expected else [])


# ---------------------------------------------------------------------------
# Decision on a mutant
# ---------------------------------------------------------------------------


def case(kept=("k1", "k2"), gone=("g1", "g2")) -> rp.MutantCase:
    return rp.MutantCase("m", "mod::f", tuple(kept), tuple(gone), "kept", "gone")


def scripted(table: dict[tuple[str, str], tuple[int, tuple[str, ...]]], mask_fork=False):
    calls: list[rp.Job] = []

    def run(job: rp.Job) -> rp.Outcome:
        calls.append(job)
        if mask_fork and job.tree == "kept" and not job.fresh:
            return rp.Outcome(0)
        code, failed = table[(job.mutant, job.tree)]
        return rp.Outcome(code, failed, 1.0)

    return run, calls


DECISION_ROWS = [
    ("kept tests kill it", (1, ("k2",)), (0, ()), "killed", "k2", ()),
    ("both survive", (0, ()), (0, ()), "proved", None, ()),
    ("only a removed test kills it", (0, ()), (1, ("g2[p]",)), "lost", "g2", ("g2",)),
    ("timeout of the kept tests counts as killed", (124, ()), (0, ()), "killed", None, ()),
    ("kill by signal counts as killed", (137, ()), (0, ()), "killed", None, ()),
    ("timeout of the removed tests is a loss", (0, ()), (124, ()), "lost", None, ("g1", "g2")),
    ("killer that is not a removed test", (0, ()), (1, ("zz",)), "lost", "zz", ("g1", "g2")),
    ("exit 2 on the kept side", (2, ()), (0, ()), "error", None, ("g1", "g2")),
    ("exit 3 on the kept side", (3, ()), (0, ()), "error", None, ("g1", "g2")),
    ("exit 4 on the kept side", (4, ()), (0, ()), "error", None, ("g1", "g2")),
    ("exit 5 on the kept side", (5, ()), (0, ()), "error", None, ("g1", "g2")),
    ("exit 5 on the removed side", (0, ()), (5, ()), "error", None, ("g1", "g2")),
]


@pytest.mark.parametrize(
    ("kept", "gone", "status", "killer", "put_back"),
    [r[1:] for r in DECISION_ROWS],
    ids=[r[0] for r in DECISION_ROWS],
)
@pytest.mark.parametrize("fork_first", [False, True], ids=["fresh", "fork"])
def test_decision_on_a_mutant(kept, gone, status, killer, put_back, fork_first):
    run, _ = scripted({("m", "kept"): kept, ("m", "gone"): gone})
    (verdict,) = rp.prove_mutants([case()], run, 2, fork_first)
    assert (verdict.status, verdict.killer, verdict.put_back) == (status, killer, put_back)


def test_a_fork_survivor_is_played_again_in_a_fresh_process():
    run, calls = scripted({("m", "kept"): (1, ("k1",)), ("m", "gone"): (0, ())}, mask_fork=True)
    (verdict,) = rp.prove_mutants([case()], run, 2, True)
    assert verdict.status == "killed"
    assert [j.fresh for j in calls if j.tree == "kept"] == [False, True]


def test_a_fork_kill_is_not_played_again():
    run, calls = scripted({("m", "kept"): (1, ("k1",)), ("m", "gone"): (0, ())})
    rp.prove_mutants([case()], run, 2, True)
    assert [(j.tree, j.fresh) for j in calls] == [("kept", False)]


def test_removed_tests_always_run_in_a_fresh_process():
    run, calls = scripted({("m", "kept"): (0, ()), ("m", "gone"): (0, ())})
    rp.prove_mutants([case()], run, 2, True)
    assert [j.fresh for j in calls if j.tree == "gone"] == [True]


def test_a_mutant_with_no_kept_test_goes_to_the_removed_tests_alone():
    run, calls = scripted({("m", "gone"): (1, ("g1",))})
    (verdict,) = rp.prove_mutants([case(kept=())], run, 2, False)
    assert verdict.status == "lost"
    assert [j.tree for j in calls] == ["gone"]


def test_a_mutant_with_no_removed_test_is_proved_when_kept_tests_miss_it():
    run, _ = scripted({("m", "kept"): (0, ())})
    (verdict,) = rp.prove_mutants([case(gone=())], run, 2, False)
    assert verdict.status == "proved"


def test_both_runners_write_the_same_result_format(tmp_path, monkeypatch):
    seen = []

    def fake_fresh(job, python, scratch_root, timeout):
        seen.append(("fresh", job.mutant))
        return rp.Outcome(1, ("t::x",), 0.1)

    monkeypatch.setattr(rp, "run_fresh", fake_fresh)
    with rp.open_runner("fresh", "py", tmp_path, 2) as run:
        outcomes = rp.run_jobs([rp.Job("a", ("t::x",), "d"), rp.Job("b", (), "d")], run, 2)
    assert outcomes == [rp.Outcome(1, ("t::x",), 0.1), rp.Outcome(0)]
    assert seen == [("fresh", "a")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FAILED tests/a.py::t[1] - assert 0\n", ("tests/a.py::t[1]",)),
        ("ERROR tests/a.py - ImportError\nFAILED tests/b.py::u\n", ("tests/a.py", "tests/b.py::u")),
        ("1 passed\n", ()),
    ],
)
def test_failed_ids_of_a_pytest_summary(tmp_path, text, expected):
    out = tmp_path / "out.txt"
    out.write_text(text, encoding="utf-8")
    assert rp.finish_run(tmp_path / "gone", out, 1, 0.0).failed == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("tests/a.py::T::t[x|y]|run", "tests/a.py::T::t"),
        ("tests/a.py::t|setup", "tests/a.py::t"),
        ("tests/a.py::t[1]", "tests/a.py::t"),
    ],
)
def test_function_id_of_a_node_or_context(node, expected):
    assert rp.function_id_of(node) == expected


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_a_killer_that_did_not_change_is_not_played_again(tmp_path):
    before = make_tree(tmp_path, "before", {"tests/unit/pkg/test_a.py": BODY.format(n="one")})
    after = make_tree(tmp_path, "after", {"tests/unit/pkg/test_a.py": BODY.format(n="one")})
    plan = {
        "mutants": [
            {"name": "m1", "status": "killed", "killer": "tests/unit/pkg/test_a.py::test_one"}
        ]
    }
    assert rp.carried_mutants(plan, before, after) == {"m1"}


@pytest.mark.parametrize(
    ("after_text", "row"),
    [
        (BODY.format(n="one").replace("== 1", "== 2"), {"status": "killed", "killer": TEST_ONE}),
        (None, {"status": "killed", "killer": TEST_ONE}),
        (BODY.format(n="one"), {"status": "proved", "killer": None}),
        (BODY.format(n="one"), {"status": "lost", "killer": TEST_ONE}),
    ],
    ids=["body changed", "killer moved", "no killer", "lost by plan"],
)
def test_a_moved_or_changed_killer_is_played_again(tmp_path, after_text, row):
    before = make_tree(tmp_path, "before", {"tests/unit/pkg/test_a.py": BODY.format(n="one")})
    after = make_tree(
        tmp_path, "after", {"tests/unit/pkg/test_a.py": after_text} if after_text else {}
    )
    assert rp.carried_mutants({"mutants": [{"name": "m1", **row}]}, before, after) == set()


def test_lost_lines_and_arcs_are_listed_per_file(tmp_path):
    tree = make_tree(tmp_path)
    before = rp.load_coverage(
        make_cov(
            tmp_path / "b",
            tree,
            {
                ctx(TEST_ONE): {IMPL_PATH: ARCS},
                ctx(TEST_TWO): {IMPL_PATH: [(1, 2), (2, 7), (7, -2)]},
            },
        ),
        tree,
    )
    after = rp.load_coverage(
        make_cov(tmp_path / "a", tree, {ctx(TEST_ONE): {IMPL_PATH: ARCS}}), tree
    )
    lost = rp.lost_items(before, after, {TEST_TWO})
    assert lost[IMPL_PATH]["lines"] == [7]
    assert lost[IMPL_PATH]["arcs"] == [[2, 7], [7, -2]]
    assert lost[IMPL_PATH]["covered_by"] == [TEST_TWO]


def test_a_lost_arc_alone_is_a_loss(tmp_path):
    tree = make_tree(tmp_path)
    full = {ctx(TEST_ONE): {IMPL_PATH: [(1, 2), (2, 3), (3, 4), (2, 4)]}}
    part = {ctx(TEST_ONE): {IMPL_PATH: [(1, 2), (2, 3), (3, 4)]}}
    before = rp.load_coverage(make_cov(tmp_path / "b", tree, full), tree)
    after = rp.load_coverage(make_cov(tmp_path / "a", tree, part), tree)
    lost = rp.lost_items(before, after, set())
    assert lost[IMPL_PATH]["lines"] == []
    assert lost[IMPL_PATH]["arcs"] == [[2, 4]]


def test_no_loss_when_the_empty_context_still_runs_it(tmp_path):
    tree = make_tree(tmp_path)
    before = rp.load_coverage(
        make_cov(tmp_path / "b", tree, {ctx(TEST_ONE): {IMPL_PATH: ARCS}}), tree
    )
    after = rp.load_coverage(make_cov(tmp_path / "a", tree, {"": {IMPL_PATH: ARCS}}), tree)
    assert rp.lost_items(before, after, {TEST_ONE}) == {}


def test_package_scope_takes_every_module_of_the_package(tmp_path):
    tree = make_tree(tmp_path)
    write(tree, "hydromodpy/zone/a.py", "A = 1\n")
    index = rp.build_index(tree)
    assert rp.package_modules(index, {IMPL_PATH}) == {
        "hydromodpy/pkg/__init__.py",
        IMPL_PATH,
        "hydromodpy/pkg/other.py",
    }
    assert rp.package_modules(index, {"hydromodpy/__init__.py"}) == {"hydromodpy/__init__.py"}


def test_moves_are_read_as_lines_or_as_a_list(tmp_path):
    (tmp_path / "b.json").write_text(
        '{"from_id": "a::t", "to_id": "b::t", "kind": "move"}\n{"from_id": "a::u", "to_id": "b::u", "kind": "move"}\n'
    )
    (tmp_path / "c.json").write_text('[{"from_id": "c::t", "to_id": "d::t", "kind": "fold"}]')
    assert [m["from_id"] for m in rp.load_moves(tmp_path)] == ["a::t", "a::u", "c::t"]
    assert rp.load_moves(None) == []


class Scene:
    """Two trees with the same library code, a suite that loses test_two, and scripted mutants."""

    def __init__(self, tmp_path: Path, monkeypatch, mutant_codes, *, after_arcs=ARCS, seconds=1.0):
        t = tmp_path
        before_tests = {
            "tests/unit/pkg/test_a.py": BODY.format(n="one"),
            "tests/unit/pkg/test_b.py": BODY.format(n="two"),
        }
        self.before = make_tree(t, "before", before_tests)
        self.after = make_tree(t, "after", {"tests/unit/pkg/test_a.py": BODY.format(n="one")})
        extra = [(1, 2), (2, 3), (3, -2)]
        contexts = {ctx(TEST_ONE): {IMPL_PATH: ARCS}, ctx(TEST_TWO): {IMPL_PATH: extra}}
        rows = [
            ("tests.unit.pkg.test_a", "test_one", "passed"),
            ("tests.unit.pkg.test_b", "test_two", "passed"),
        ]
        self.mb = make_measure(t / "mb", self.before, contexts, rows)
        self.ma = make_measure(
            t / "ma", self.after, {ctx(TEST_ONE): {IMPL_PATH: after_arcs}}, rows[:1]
        )
        self.run_dir = t / "run"
        self.modules: list[str] = []
        for rel in (IMPL_PATH, "hydromodpy/pkg/other.py"):
            names = (
                {MUTANT: 33} if rel == IMPL_PATH else {"hydromodpy.pkg.other.x_twice__mutmut_1": 33}
            )
            write(self.run_dir, f"{rel}.meta", json.dumps({"exit_code_by_key": names}))
        self.calls: list[rp.Job] = []
        self.codes = mutant_codes
        self.seconds = seconds
        monkeypatch.setattr(rp, "require_mutmut", lambda python: None)
        monkeypatch.setattr(rp, "generate_mutants", self.generate)
        monkeypatch.setattr(rp, "swap_tests", lambda mutants, tree, work: mutants)
        monkeypatch.setattr(rp, "open_runner", self.open_runner)

    def generate(self, tree, modules, work, python, selection):
        self.modules = list(modules)
        return self.run_dir

    @contextlib.contextmanager
    def open_runner(self, kind, python, work, processes, timeout=0):
        yield self.run

    def run(self, job: rp.Job) -> rp.Outcome:
        self.calls.append(job)
        if job.mutant == "":
            return rp.Outcome(0, (), self.seconds)
        return rp.Outcome(*self.codes[job.ids[0].split("::")[0].rsplit("/", 1)[-1]])

    def args(self, tmp_path: Path, **over) -> list[str]:
        base = [
            "check", "--before", str(self.before), "--after", str(self.after), "--mutmut", "py",
            "--work", str(tmp_path / "work"), "--out", str(tmp_path / "check.json"),
            "--measure-before", str(self.mb), "--measure-after", str(self.ma), "--processes", "2",
        ]  # fmt: skip
        for flag, value in over.items():
            base += [f"--{flag.replace('_', '-')}", str(value)]
        return base


KILLED_BY_ONE = {"test_a.py": (1, ("tests/unit/pkg/test_a.py::test_one",)), "test_b.py": (0, ())}
KILLED_BY_TWO_ONLY = {
    "test_a.py": (0, ()),
    "test_b.py": (1, ("tests/unit/pkg/test_b.py::test_two",)),
}


def test_check_is_proved_when_the_kept_tests_still_kill(tmp_path, monkeypatch, capsys):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE)
    assert rp.main(scene.args(tmp_path)) == 0
    result = json.loads((tmp_path / "check.json").read_text())
    assert result["lost_coverage"] == {} and result["lost_mutants"] == []
    assert result["mutants"]["killed"] == 1 and result["removed_ids"] == 1
    assert scene.modules == [IMPL_PATH]


def test_check_gives_1_and_names_the_mutant_only_a_removed_test_kills(tmp_path, monkeypatch):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_TWO_ONLY)
    assert rp.main(scene.args(tmp_path)) == 1
    result = json.loads((tmp_path / "check.json").read_text())
    assert result["lost_mutants"][0]["name"] == MUTANT
    assert result["lost_mutants"][0]["put_back"] == [TEST_TWO]
    assert result["restore_files"] == ["tests/unit/pkg/test_b.py"]


def test_check_gives_1_on_a_lost_arc(tmp_path, monkeypatch):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE, after_arcs=[(-1, 1), (1, 2), (2, 3)])
    assert rp.main(scene.args(tmp_path)) == 1
    result = json.loads((tmp_path / "check.json").read_text())
    assert result["lost_coverage"][IMPL_PATH]["arcs"] == [[3, -2]]
    assert result["lost_coverage"][IMPL_PATH]["covered_by"] == [TEST_TWO]


def test_check_scope_package_adds_the_modules_of_the_package(tmp_path, monkeypatch):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE)
    rp.main(scene.args(tmp_path, scope="package"))
    assert sorted(scene.modules) == [
        "hydromodpy/pkg/__init__.py",
        IMPL_PATH,
        "hydromodpy/pkg/other.py",
    ]


def test_check_does_not_play_a_mutant_the_plan_killed_with_an_unchanged_test(tmp_path, monkeypatch):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "removed": [],
                "unconditional": [],
                "mutants": [{"name": MUTANT, "status": "killed", "killer": TEST_ONE}],
            }
        )
    )
    assert rp.main(scene.args(tmp_path, plan=plan)) == 1
    assert not [j for j in scene.calls if j.mutant == MUTANT]
    assert json.loads((tmp_path / "check.json").read_text())["unaccounted_ids"] == [TEST_TWO]


def test_check_lists_a_removed_test_that_nothing_accounts_for(tmp_path, monkeypatch):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE)
    moves = tmp_path / "moves"
    moves.mkdir()
    (moves / "b.json").write_text(
        json.dumps(
            {
                "from_id": TEST_TWO + "[x]",
                "to_id": "tests/unit/pkg/test_a.py::test_one",
                "kind": "fold",
            }
        )
        + "\n"
    )
    assert rp.main(scene.args(tmp_path, moves=moves)) == 0
    assert json.loads((tmp_path / "check.json").read_text())["removed_ids"] == 0


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


class PlanScene(Scene):
    def __init__(self, tmp_path, monkeypatch, budget_hours=10.0):
        super().__init__(tmp_path, monkeypatch, KILLED_BY_ONE)
        self.tmp = tmp_path
        self.tree = self.before
        make_measure(
            tmp_path / "m",
            self.tree,
            {ctx(TEST_ONE): {IMPL_PATH: ARCS}, ctx(TEST_TWO): {IMPL_PATH: ARCS}, "": {}},
            [
                ("tests.unit.pkg.test_a", "test_one", "passed"),
                ("tests.unit.pkg.test_b", "test_two", "passed"),
            ],
        )
        write(
            self.tree,
            "tests/unit/pkg/test_b.py",
            LONG_TWO + "\n\ndef test_pad():\n    pass\n",
        )
        (tmp_path / "keep.txt").write_text("# kept by name\n")
        self.args_ns = Namespace(
            tree=str(self.tree), measure=str(tmp_path / "m"), keep=str(tmp_path / "keep.txt"), mutmut="py",
            work=str(tmp_path / "w"), out=str(tmp_path / "plan.json"), scope_dir=["tests/unit"],
            budget_hours=budget_hours, runner="fresh", processes=2,
        )  # fmt: skip

    def plan(self) -> dict:
        assert rp.run_plan(self.args_ns) == 0
        return json.loads((self.tmp / "plan.json").read_text())


def test_plan_removes_the_longer_duplicate_and_proves_its_mutants(tmp_path, monkeypatch):
    plan = PlanScene(tmp_path, monkeypatch).plan()
    assert [r["id"] for r in plan["removed"]] == [TEST_TWO]
    assert plan["removed"][0]["subjects"] == [IMPL_PATH]
    assert plan["mutants"] == [
        {
            "name": MUTANT,
            "function": "hydromodpy.pkg.impl::Thing.run",
            "status": "killed",
            "killer": TEST_ONE,
        }
    ]
    assert plan["put_back"] == []
    assert plan["lines"]["removed"] == 5 and plan["format"] == "hmp-removal-plan/1"
    assert set(plan["tests_sha256"]) == {"tests/unit/pkg/test_b.py"}


def test_plan_keeps_a_function_whose_module_the_budget_does_not_reach(tmp_path, monkeypatch):
    plan = PlanScene(tmp_path, monkeypatch, budget_hours=0.0).plan()
    assert plan["removed"] == []
    assert plan["put_back"] == [{"id": TEST_TWO, "reason": "module_not_proved"}]
    assert plan["hours_to_200k"] == 0.0


def test_plan_puts_back_a_function_a_mutant_needs(tmp_path, monkeypatch):
    scene = PlanScene(tmp_path, monkeypatch)
    scene.codes = KILLED_BY_TWO_ONLY
    plan = scene.plan()
    assert plan["removed"] == []
    assert plan["put_back"][0]["id"] == TEST_TWO and plan["put_back"][0]["mutant"] == MUTANT


def test_plan_skips_the_files_of_the_keep_list(tmp_path, monkeypatch):
    scene = PlanScene(tmp_path, monkeypatch)
    (tmp_path / "keep.txt").write_text("tests/unit/pkg/test_b.py  # named by a workflow\n")
    scene.codes = {"test_a.py": (0, ()), "test_b.py": (0, ())}
    plan = scene.plan()
    assert plan["skipped"]["keep"] == ["tests/unit/pkg/test_b.py::test_pad", TEST_TWO]
    assert [r["id"] for r in plan["removed"]] == [TEST_ONE]


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

APPLY_FILE = """\
import numpy as np
import pytest

from hydromodpy.pkg.impl import Thing


@pytest.fixture
def helper():
    return np.zeros(2)


@pytest.fixture
def shared():
    return 1


@pytest.fixture(autouse=True)
def always():
    return 2


@pytest.mark.parametrize("n", [1, 2])
def test_decorated(n, helper):
    assert helper is not None


def test_kept(shared):
    assert Thing


class TestAll:
    def test_one(self):
        assert 1

    def test_two(self):
        assert 2


class TestSome:
    def test_one(self):
        assert 1

    def test_two(self):
        assert 2
"""


def apply_to(tmp_path: Path, files: dict[str, str], ids: list[str], extra: dict | None = None):
    tree = make_tree(tmp_path, tests=files)
    plan = {
        "tree": "elsewhere",
        "removed": [{"id": i, "file": i.split("::")[0]} for i in ids],
        "unconditional": [],
        "tests_sha256": {rel: rp.sha256_of(tree / rel) for rel in {i.split("::")[0] for i in ids}},
    }
    formatted: list = []
    summary = rp.apply_plan(plan, tree, lambda paths, root: formatted.extend(paths))
    return tree, summary, formatted


F = "tests/unit/pkg/test_f.py"


def test_apply_removes_a_decorated_function_with_its_decorator(tmp_path):
    tree, _, formatted = apply_to(tmp_path, {F: APPLY_FILE}, [f"{F}::test_decorated"])
    text = (tree / F).read_text()
    assert "test_decorated" not in text and "parametrize" not in text
    assert "def test_kept" in text and formatted == [tree / F]


def test_apply_removes_a_class_whose_methods_all_leave(tmp_path):
    ids = [f"{F}::TestAll::test_one", f"{F}::TestAll::test_two", f"{F}::TestSome::test_one"]
    tree, _, _ = apply_to(tmp_path, {F: APPLY_FILE}, ids)
    text = (tree / F).read_text()
    assert "TestAll" not in text and "class TestSome" in text
    assert "def test_two" in text and text.count("def test_one") == 0


def test_apply_deletes_a_file_with_no_test_left(tmp_path):
    source = "def test_a():\n    assert 1\n"
    tree, summary, formatted = apply_to(tmp_path, {F: source}, [f"{F}::test_a"])
    assert not (tree / F).exists() and summary["deleted"] == [F] and formatted == []


def test_apply_keeps_an_emptied_file_that_another_test_cites(tmp_path):
    files = {
        F: "def test_a():\n    assert 1\n\n\ndef helper():\n    return 1\n",
        "tests/unit/pkg/test_g.py": "from tests.unit.pkg.test_f import helper\n",
    }
    tree, summary, _ = apply_to(tmp_path, files, [f"{F}::test_a"])
    assert (tree / F).exists() and "helper" in (tree / F).read_text() and summary["deleted"] == []


def test_apply_removes_the_fixtures_no_test_asks_for_any_more(tmp_path):
    ids = [f"{F}::test_decorated"]
    tree, _, _ = apply_to(tmp_path, {F: APPLY_FILE}, ids)
    text = (tree / F).read_text()
    assert "def helper" not in text
    assert "def shared" in text and "def always" in text


def test_apply_drops_the_imports_only_the_removed_code_used(tmp_path):
    tree, _, _ = apply_to(tmp_path, {F: APPLY_FILE}, [f"{F}::test_decorated"])
    text = (tree / F).read_text()
    assert "numpy" not in text and "import pytest" in text and "import Thing" in text


def test_apply_never_touches_conftest_or_helpers(tmp_path):
    files = {
        "tests/unit/conftest.py": "def test_x():\n    pass\n",
        "tests/_helpers/h.py": "def test_y():\n    pass\n",
    }
    tree, summary, formatted = apply_to(
        tmp_path, files, ["tests/unit/conftest.py::test_x", "tests/_helpers/h.py::test_y"]
    )
    assert (tree / "tests/unit/conftest.py").read_text() == "def test_x():\n    pass\n"
    assert (tree / "tests/_helpers/h.py").exists() and formatted == []


def test_apply_refuses_tests_that_changed_since_the_plan(tmp_path):
    tree = make_tree(tmp_path, tests={F: "def test_a():\n    pass\n"})
    plan = {
        "tree": "T0",
        "removed": [{"id": f"{F}::test_a", "file": F}],
        "unconditional": [],
        "tests_sha256": {F: "0" * 64},
    }
    with pytest.raises(rp.Refusal, match="the plan was made on T0, whose tests differ from"):
        rp.apply_plan(plan, tree, lambda *_: None)


# ---------------------------------------------------------------------------
# Refusals, each with exit code 2
# ---------------------------------------------------------------------------


class Done(SimpleNamespace):
    returncode = 0
    stdout = ""


def cli(action: str, **options: object) -> list[str]:
    flags = [(f"--{k.replace('_', '-')}", str(v)) for k, v in options.items()]
    return [action, *(part for flag in flags for part in flag)]


def test_a_differing_library_is_refused_with_2(tmp_path, capsys):
    before, after = make_tree(tmp_path, "t0"), make_tree(tmp_path, "t1")
    write(after, "hydromodpy/extra.py", "X = 1\n")
    argv = cli(
        "check", before=before, after=after, mutmut="py", work=tmp_path / "w", out=tmp_path / "o"
    )
    assert rp.main(argv) == 2
    assert capsys.readouterr().err.strip() == (
        "hydromodpy/ differs between the two trees: "
        "prove a test removal on unchanged code, in a change of its own."
    )


def test_a_missing_mutmut_is_refused_with_2(tmp_path, monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError("py")

    monkeypatch.setattr(rp.subprocess, "run", missing)
    plan = cli("plan", tree=tmp_path, measure="m", keep="k", mutmut="py", work="w", out="o")
    assert rp.main([*plan, "--scope-dir", "tests"]) == 2
    assert capsys.readouterr().err.strip() == (
        "mutmut 3.8.0 is needed for the mutant proof: "
        "pass --mutmut <python of an environment that has it>."
    )


def test_a_plan_of_another_tree_is_refused_with_2(tmp_path, capsys):
    tree = make_tree(tmp_path, "t0", {F: "def test_a():\n    pass\n"})
    row = {"id": f"{F}::test_a", "file": F}
    plan = {"tree": "T0", "removed": [row], "unconditional": [], "tests_sha256": {F: "0" * 64}}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    assert rp.main(cli("apply", plan=tmp_path / "plan.json", tree=tree)) == 2
    expected = (
        f"the plan was made on T0, whose tests differ from {tree.resolve()}: make the plan again."
    )
    assert capsys.readouterr().err.strip() == expected


def test_something_that_is_not_a_measure_is_refused_with_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rp, "require_mutmut", lambda python: None)
    tree = make_tree(tmp_path, "t0")
    plan = cli(
        "plan", tree=tree, measure=tmp_path / "none", keep="k", mutmut="py", work="w", out="o"
    )
    assert rp.main([*plan, "--scope-dir", "tests"]) == 2
    expected = (
        f"{tmp_path / 'none'} is not a measure: run `removal_proof.py measure` on the tree first."
    )
    assert capsys.readouterr().err.strip() == expected


def measure_args(tmp_path: Path) -> list[str]:
    tree = make_tree(tmp_path, "mt")
    return ["measure", "--tree", str(tree), "--out", str(tmp_path / "out")]


def test_measure_refuses_coverage_before_7_10(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rp.importlib.metadata, "version", lambda name: "7.9.2")
    assert rp.main(measure_args(tmp_path)) == 2
    assert (
        capsys.readouterr().err.strip()
        == "coverage 7.10 or later is needed to measure child processes."
    )


def test_measure_refuses_a_library_imported_from_elsewhere(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rp.importlib.metadata, "version", lambda name: "7.16.0")
    monkeypatch.setattr(
        rp, "library_location", lambda python, tree, cwd: "/elsewhere/hydromodpy/__init__.py"
    )
    assert rp.main(measure_args(tmp_path)) == 2
    tree = (tmp_path / "mt").resolve()
    assert (
        capsys.readouterr().err.strip()
        == f"hydromodpy is imported from /elsewhere/hydromodpy/__init__.py, not from {tmp_path / 'mt'}: run the measure on the tree itself."
    )
    assert tree.exists()


def test_measure_refuses_a_red_suite(tmp_path, monkeypatch, capsys):
    tree = make_tree(tmp_path, "mt")
    monkeypatch.setattr(rp.importlib.metadata, "version", lambda name: "7.16.0")
    monkeypatch.setattr(
        rp, "library_location", lambda python, tree, cwd: str(tree / "hydromodpy/__init__.py")
    )
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: Done(returncode=1))
    assert rp.main(["measure", "--tree", str(tree), "--out", str(tmp_path / "out")]) == 2
    assert (
        capsys.readouterr().err.strip()
        == f"the measure of {tree} has failing tests: a removal is proven on a green suite only."
    )


def test_measure_writes_the_coverage_configuration_and_the_results(tmp_path, monkeypatch):
    tree = make_tree(tmp_path, "mt", {"tests/unit/test_x.py": "def test_x():\n    pass\n"})
    out = tmp_path / "out"
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        out.joinpath("junit.xml").write_text(junit([("tests.unit.test_x", "test_x", "passed")]))
        make_cov(out, tree, {ctx("tests/unit/test_x.py::test_x"): {IMPL_PATH: ARCS}})
        return Done()

    monkeypatch.setattr(
        rp, "library_location", lambda python, tree, cwd: str(tree / "hydromodpy/__init__.py")
    )
    monkeypatch.setattr(rp.subprocess, "run", fake_run)
    meta = rp.run_measure(tree, out, ["tests/unit"], ["tests/unit/skip.py"], 4)
    rc = (out / "coveragerc.toml").read_text()
    assert 'patch = ["subprocess"]' in rc and "branch = true" in rc and "parallel = true" in rc
    assert (
        'concurrency = ["thread", "multiprocessing"]' in rc
        and f'data_file = "{out}/.coverage"' in rc
    )
    command = commands[0][0]
    assert (
        "--cov-context=test" in command
        and "--ignore=tests/unit/skip.py" in command
        and "-n" in command
    )
    assert commands[0][1]["env"]["PYTHONPATH"] == str(tree) and commands[0][1]["env"][
        "COVERAGE_FILE"
    ] == str(out / ".coverage")
    assert (
        meta["cases"] == 1
        and (out / "ids.txt").read_text().strip() == "tests/unit/test_x.py::test_x"
    )
    assert set(json.loads((out / "meta.json").read_text())["hydromodpy_sha256"]) >= {
        "hydromodpy/pkg/impl.py"
    }


@pytest.mark.parametrize(
    ("version", "reply", "fails"),
    [("3.8.0", "3.8.0\n", False), ("3.7.0", "3.7.0\n", True), ("none", "", True)],
    ids=["right version", "another version", "mutmut absent"],
)
def test_the_mutmut_version_is_checked(monkeypatch, version, reply, fails):
    monkeypatch.setattr(
        rp.subprocess, "run", lambda *a, **k: Done(returncode=0 if reply else 1, stdout=reply)
    )
    if fails:
        with pytest.raises(rp.Refusal, match="mutmut 3.8.0 is needed for the mutant proof"):
            rp.require_mutmut("py")
    else:
        rp.require_mutmut("py")


@pytest.mark.parametrize(
    ("version", "fails"), [("7.9.9", True), ("7.10.0", False), ("7.16.0", False), ("6.5", True)]
)
def test_the_coverage_version_is_checked(version, fails):
    if fails:
        with pytest.raises(rp.Refusal, match="coverage 7.10 or later"):
            rp.require_coverage(version)
    else:
        rp.require_coverage(version)


def test_check_refuses_a_proof_over_its_budget(tmp_path, monkeypatch, capsys):
    scene = Scene(tmp_path, monkeypatch, KILLED_BY_ONE, seconds=600.0)
    assert rp.main(scene.args(tmp_path, budget_minutes=1)) == 2
    assert (
        capsys.readouterr().err.strip()
        == "the mutant proof needs 6.2 minutes, over the budget of 1.0: split the removal."
    )


def test_the_command_line_has_the_documented_actions():
    parser = rp.build_parser()
    for action in ("measure", "plan", "apply", "check", "replay"):
        with pytest.raises(SystemExit) as stop:
            parser.parse_args([action, "--help"])
        assert stop.value.code == 0
    args = parser.parse_args(
        [
            "replay",
            "--run-dir",
            "d",
            "--names",
            "n",
            "--mutmut",
            "p",
            "--work",
            "w",
            "--out",
            "o",
            "--tests",
            "t",
        ]
    )
    assert (args.runner, args.processes) == ("fresh", 16)


def test_a_fork_worker_and_a_fresh_run_share_the_pytest_arguments(tmp_path):
    args = rp.pytest_args(tmp_path / "ids.txt", True)
    assert args[0] == f"@{tmp_path / 'ids.txt'}" and "-x" in args and "-rfE" in args
    assert "-x" not in rp.pytest_args(tmp_path / "ids.txt", False)


@pytest.mark.parametrize(("status", "code"), [(3 << 8, 3), (9, 137), (0, 0)])
def test_a_child_gives_its_exit_code_or_128_plus_its_signal(monkeypatch, status, code):
    monkeypatch.setattr(rp.os, "waitpid", lambda pid, flags: (pid, status))
    assert rp.wait_child(123, 5.0) == code


def test_a_child_that_exceeds_its_time_is_killed_and_gives_124(monkeypatch):
    killed = []
    monkeypatch.setattr(rp.os, "waitpid", lambda pid, flags: (0, 0) if flags else (pid, 9))
    monkeypatch.setattr(rp.os, "killpg", lambda pid, sig: killed.append(pid))
    assert rp.wait_child(123, 0.05) == 124
    assert killed == [123]
