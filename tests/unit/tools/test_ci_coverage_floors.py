"""Tests of the coverage floors: tables over a fabricated tree and fabricated coverage data."""

from __future__ import annotations

from pathlib import Path

import pytest
from coverage import CoverageData

from tools.ci import coverage_floors as cf

STRAIGHT = "a = 1\nb = 2\nc = 3\n"
BRANCH = "x = 1\nif x:\n    y = 2\nz = 3\n"
STRAIGHT_ARCS = [(-1, 1), (1, 2), (2, 3), (3, -1)]
BRANCH_ARCS = [(-1, 1), (1, 2), (2, 3), (3, 4), (4, -1), (2, 4)]

TREE = {
    "hydromodpy/__init__.py": "",
    "hydromodpy/pkg/__init__.py": "",
    "hydromodpy/pkg/top.py": STRAIGHT,
    "hydromodpy/pkg/alpha/__init__.py": "",
    "hydromodpy/pkg/alpha/a.py": BRANCH,
    "hydromodpy/pkg/beta/b.py": STRAIGHT,
    "hydromodpy/pkg/beta/deep/c.py": STRAIGHT,
    "hydromodpy/pkg/dataonly/table.json": "{}",
}
# top.py runs two lines of three, a.py runs every arc, c.py runs every arc, b.py never runs.
ARCS = {
    "hydromodpy/pkg/top.py": [(-1, 1), (1, 2)],
    "hydromodpy/pkg/alpha/a.py": BRANCH_ARCS,
    "hydromodpy/pkg/beta/deep/c.py": STRAIGHT_ARCS,
}
HEADER = "# The floors only rise.\n[floors]\n"
FULL_TABLE = (
    HEADER
    + '"hydromodpy/pkg/*.py" = 66.5\n'
    + '"hydromodpy/pkg/alpha" = 100.0\n'
    + '"hydromodpy/pkg/beta" = 0.0\n'
    + '"hydromodpy/pkg/beta/deep" = 100.0\n'
)


def write_tree(root: Path, files: dict[str, str] = TREE) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def write_data(root: Path, arcs: dict[str, list[tuple[int, int]]] = ARCS) -> Path:
    data_file = root / ".coverage"
    data = CoverageData(basename=str(data_file))
    data.add_arcs({str((root / rel).resolve()): list(pairs) for rel, pairs in arcs.items()})
    data.write()
    return data_file


def write_table(root: Path, text: str) -> Path:
    table = root / "floors.toml"
    table.write_text(text, encoding="utf-8")
    return table


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = write_tree(tmp_path / "tree")
    write_data(root)
    return root


def test_the_tree_asks_one_key_per_package_and_per_second_level_sub_package(tree):
    assert cf.tree_keys(tree) == [
        "hydromodpy/pkg/*.py",
        "hydromodpy/pkg/alpha",
        "hydromodpy/pkg/beta",
    ]


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (
            ["hydromodpy/pkg/*.py", "hydromodpy/pkg/beta", "hydromodpy/pkg/beta/deep"],
            {
                "hydromodpy/pkg/*.py": ["__init__.py", "top.py"],
                "hydromodpy/pkg/beta": ["b.py"],
                "hydromodpy/pkg/beta/deep": ["c.py"],
            },
        ),
        (
            ["hydromodpy/pkg/*.py", "hydromodpy/pkg/beta"],
            {
                "hydromodpy/pkg/*.py": ["__init__.py", "top.py"],
                "hydromodpy/pkg/beta": ["b.py", "c.py"],
            },
        ),
        (["hydromodpy/pkg/gone"], {"hydromodpy/pkg/gone": []}),
    ],
    ids=["deepest key wins", "parent key keeps deeper files", "absent path"],
)
def test_a_file_counts_in_the_deepest_key_that_holds_it(tree, keys, expected):
    held = cf.assign_files(tree, keys)
    assert {key: [path.name for path in paths] for key, paths in held.items()} == expected


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        pytest.param(FULL_TABLE, [], id="floors hold"),
        pytest.param(
            FULL_TABLE.replace("66.5", "70.0"),
            ["hydromodpy/pkg/*.py 66.67 < 70.0"],
            id="floor missed",
        ),
        pytest.param(
            FULL_TABLE.replace('"hydromodpy/pkg/beta" = 0.0\n', ""),
            ["hydromodpy/pkg/beta has no floor: run coverage_floors.py measure"],
            id="sub-package without a line",
        ),
        pytest.param(
            FULL_TABLE + '"hydromodpy/pkg/gone" = 0.0\n',
            ["hydromodpy/pkg/gone names no module of the tree: fix the path or remove the line"],
            id="path absent from the tree",
        ),
        pytest.param(
            FULL_TABLE.replace('"hydromodpy/pkg/beta/deep" = 100.0\n', "").replace(
                '"hydromodpy/pkg/beta" = 0.0', '"hydromodpy/pkg/beta" = 60.0'
            ),
            ["hydromodpy/pkg/beta 50.00 < 60.0"],
            id="a parent key counts its deeper files",
        ),
        pytest.param(
            FULL_TABLE.replace("100.0", "99.0", 1),
            [],
            id="a floor under the measure holds",
        ),
    ],
)
def test_check_names_every_floor_missed_and_every_line_to_fix(tree, table, expected):
    problems = cf.check(write_table(tree, table), tree / ".coverage", tree)
    assert problems == expected


def test_a_branch_left_out_lowers_the_measure_below_the_lines(tree):
    arcs = {**ARCS, "hydromodpy/pkg/alpha/a.py": [pair for pair in BRANCH_ARCS if pair != (2, 4)]}
    data_file = write_data(tree, arcs)
    measures, absent = cf.measure_keys(data_file, tree, ["hydromodpy/pkg/alpha"])
    assert absent == []
    assert measures["hydromodpy/pkg/alpha"] == pytest.approx(100 * 5 / 6)


def test_a_module_that_never_ran_counts_for_zero(tree):
    measures, _ = cf.measure_keys(
        tree / ".coverage", tree, ["hydromodpy/pkg/beta", "hydromodpy/pkg/beta/deep"]
    )
    assert measures["hydromodpy/pkg/beta"] == 0.0


def test_a_sub_package_without_statement_measures_one_hundred(tmp_path):
    root = write_tree(
        tmp_path / "empty", {"hydromodpy/__init__.py": "", "hydromodpy/pkg/__init__.py": ""}
    )
    write_tree(root, {"hydromodpy/pkg/sub/__init__.py": "", "hydromodpy/pkg/other.py": "a = 1\n"})
    data_file = write_data(root, {"hydromodpy/pkg/other.py": [(-1, 1), (1, -1)]})
    measures, _ = cf.measure_keys(data_file, root, ["hydromodpy/pkg/sub"])
    assert measures == {"hydromodpy/pkg/sub": 100.0}


@pytest.mark.parametrize(
    ("old", "measure", "expected"),
    [
        (50.0, 66.67, 66.0),
        (90.0, 66.67, 90.0),
        (0.0, 83.33, 82.5),
        (0.0, 100.0, 99.5),
        (0.0, 0.2, 0.0),
        (99.1, 99.3, 99.1),
        (0.0, 80.5, 80.0),
    ],
    ids=[
        "rises",
        "never lowers",
        "rounds down to 0.5",
        "full coverage",
        "tiny measure",
        "odd old floor",
        "exact half",
    ],
)
def test_a_floor_is_the_measure_minus_half_a_point_rounded_down_and_never_lower(
    old, measure, expected
):
    assert cf.raised(old, measure) == expected


def test_measure_write_raises_in_place_keeps_comments_and_adds_new_keys_sorted(tree):
    table = write_table(
        tree,
        HEADER
        + '"hydromodpy/pkg/alpha" = 50.0 # lost two files in 6.2\n'
        + '"hydromodpy/pkg/beta" = 10.0\n'
        + '"hydromodpy/pkg/beta/deep" = 100.0\n',
    )
    report, absent = cf.measure(table, tree / ".coverage", tree, write=True)
    assert absent == []
    assert report == [
        "hydromodpy/pkg/*.py 66.67 new -> 66.0",
        "hydromodpy/pkg/alpha 100.00 50.0 -> 99.5",
        "hydromodpy/pkg/beta 0.00 10.0 -> 10.0",
        "hydromodpy/pkg/beta/deep 100.00 100.0 -> 100.0",
    ]
    assert table.read_text(encoding="utf-8") == (
        HEADER
        + '"hydromodpy/pkg/*.py" = 66.0\n'
        + '"hydromodpy/pkg/alpha" = 99.5 # lost two files in 6.2\n'
        + '"hydromodpy/pkg/beta" = 10.0\n'
        + '"hydromodpy/pkg/beta/deep" = 100.0\n'
    )
    assert cf.check(table, tree / ".coverage", tree) == ["hydromodpy/pkg/beta 0.00 < 10.0"]


def test_measure_without_write_leaves_the_table_alone(tree):
    table = write_table(tree, FULL_TABLE)
    before = table.read_text(encoding="utf-8")
    report, _ = cf.measure(table, tree / ".coverage", tree, write=False)
    assert len(report) == 4
    assert table.read_text(encoding="utf-8") == before


def test_a_new_sub_package_enters_the_table_from_zero_and_rises_with_its_measure(tree):
    table = write_table(tree, HEADER + '"hydromodpy/pkg/*.py" = 66.0\n')
    cf.measure(table, tree / ".coverage", tree, write=True)
    floors = cf.load_floors(table)
    assert floors == {
        "hydromodpy/pkg/*.py": 66.0,
        "hydromodpy/pkg/alpha": 99.5,
        "hydromodpy/pkg/beta": 49.5,
    }


REFUSALS = [
    pytest.param("data_missing", "does not exist: run coverage combine first", id="no data file"),
    pytest.param("other_tree", "holds no file under", id="data of another tree"),
    pytest.param(
        "lines_only", "holds no branch data: run pytest with --cov-branch", id="no branch data"
    ),
]


@pytest.mark.parametrize(("case", "phrase"), REFUSALS)
def test_check_refuses_coverage_data_it_cannot_use(tmp_path, capsys, case, phrase):
    root = write_tree(tmp_path / "tree")
    table = write_table(root, FULL_TABLE)
    data_file = root / ".coverage"
    if case == "other_tree":
        other = write_tree(tmp_path / "other")
        data_file = write_data(other)
    if case == "lines_only":
        data = CoverageData(basename=str(data_file))
        data.add_lines({str((root / "hydromodpy/pkg/top.py").resolve()): [1, 2]})
        data.write()
    code = cf.main(["check", str(table), "--data-file", str(data_file), "--root", str(root)])
    assert code == 1
    assert phrase in capsys.readouterr().err


TABLE_REFUSALS = [
    pytest.param("[floors]\n", "has no [floors] table", id="empty table"),
    pytest.param("[other]\na = 1\n", "has no [floors] table", id="no floors section"),
    pytest.param(
        '[floors]\n"hydromodpy/pkg/alpha" = 101\n',
        "must be a percentage from 0 to 100",
        id="over 100",
    ),
    pytest.param(
        '[floors]\n"hydromodpy/pkg/alpha" = -1\n',
        "must be a percentage from 0 to 100",
        id="negative",
    ),
    pytest.param(
        '[floors]\n"hydromodpy/pkg/alpha" = "high"\n',
        "must be a percentage from 0 to 100",
        id="text",
    ),
    pytest.param("[floors\n", "is not valid TOML", id="broken TOML"),
]


@pytest.mark.parametrize(("text", "phrase"), TABLE_REFUSALS)
def test_check_refuses_a_table_that_is_not_a_table_of_percentages(tree, capsys, text, phrase):
    table = write_table(tree, text)
    code = cf.main(
        ["check", str(table), "--data-file", str(tree / ".coverage"), "--root", str(tree)]
    )
    assert code == 1
    assert phrase in capsys.readouterr().err


def test_check_refuses_a_table_that_does_not_exist(tree, capsys):
    code = cf.main(
        [
            "check",
            str(tree / "none.toml"),
            "--data-file",
            str(tree / ".coverage"),
            "--root",
            str(tree),
        ]
    )
    assert code == 1
    assert "none.toml does not exist" in capsys.readouterr().err


def test_main_prints_each_failure_and_exits_one(tree, capsys):
    table = write_table(tree, FULL_TABLE.replace("66.5", "70.0"))
    args = ["--data-file", str(tree / ".coverage"), "--root", str(tree)]
    assert cf.main(["check", str(table), *args]) == 1
    assert capsys.readouterr().out == "hydromodpy/pkg/*.py 66.67 < 70.0\n"
    table = write_table(tree, FULL_TABLE)
    assert cf.main(["check", str(table), *args]) == 0
    assert capsys.readouterr().out == "4 floors hold\n"


def test_check_reads_the_data_file_that_coverage_file_names(tree, capsys, monkeypatch):
    table = write_table(tree, FULL_TABLE)
    monkeypatch.chdir(tree.parent)
    monkeypatch.setenv("COVERAGE_FILE", str(tree / ".coverage"))
    assert cf.main(["check", str(table), "--root", str(tree)]) == 0
    assert capsys.readouterr().out == "4 floors hold\n"


def test_measure_exits_one_when_a_line_names_an_absent_path(tree, capsys):
    table = write_table(tree, FULL_TABLE + '"hydromodpy/pkg/gone" = 0.0\n')
    args = ["--data-file", str(tree / ".coverage"), "--root", str(tree)]
    assert cf.main(["measure", str(table), *args]) == 1
    assert "hydromodpy/pkg/gone names no module of the tree" in capsys.readouterr().out
