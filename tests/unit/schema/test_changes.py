"""The register of changes is read once, checked row by row, and holds the delay of an old form."""

from __future__ import annotations

import pytest

from hydromodpy.schema.changes import (
    DELAY_MINORS,
    FIRST_EDITION,
    REGISTER,
    Bug,
    Migration,
    editions,
    migrations_of,
    outlived,
    prerelease_refusal,
    read,
    removal_of,
)

HEAD = 'schema = "hydromodpy.changes.v1"\n'

BUG = '[[bug]]\nid = "b"\nsince = "2.1.0"\nversions = "<2.1.0"\nquantities = ["metrics"]\ntext = "t"\n'
RECIPE = '[[recipe]]\nid = "r"\nsince = "2.1.0"\neffect = "refusal"\nquantities = []\ntext = "t"\n'
DEFAULT = (
    '[[default]]\nid = "d"\nsince = "2.1.0"\nedition = "2.1"\nkey = "solver.x"\nold = 0.5\n'
    'new = 0.45\nquantities = ["metrics"]\ntext = "t"\n'
)
MOVE = '[[migration]]\ndocument = "config"\nold = "a.b"\nnew = "a.c"\nsince = "2.1.0"\n'


def test_the_shipped_register_reads_and_holds_every_table() -> None:
    assert {bug.id for bug in REGISTER.bugs} >= {
        "discharge_scores_before_period_alignment",
        "voronoi_nwt_boussinesq_fixes_2026_10_09",
        "mf6_computation_top",
    }
    assert REGISTER.recipes and REGISTER.migrations
    ids = [row.id for row in (*REGISTER.bugs, *REGISTER.defaults, *REGISTER.recipes)]
    assert len(ids) == len(set(ids))


def test_a_good_register_reads_into_its_rows() -> None:
    register = read(HEAD + BUG + RECIPE + DEFAULT + MOVE)

    assert register.bugs == (
        Bug(id="b", since="2.1.0", versions="<2.1.0", quantities=("metrics",), text="t"),
    )
    assert register.recipes[0].effect == "refusal"
    assert register.defaults[0].old == 0.5
    assert register.migrations == (
        Migration(document="config", since="2.1.0", old="a.b", new="a.c"),
    )


FAULTS = {
    "no schema": (BUG, "schema must be"),
    "an unknown top-level key": (HEAD + "other = 1\n", "unknown top-level key 'other'"),
    "a table that is no array": (HEAD + "[bug]\nid = 'x'\n", "must be an array of tables"),
    "a missing field": (HEAD + BUG.replace('text = "t"\n', ""), "missing field 'text'"),
    "an unknown field": (HEAD + BUG + "colour = 1\n", "unknown field 'colour'"),
    "a bad id": (HEAD + BUG.replace('id = "b"', 'id = "B-1"'), "id must match"),
    "an id used by two tables": (
        HEAD + BUG + RECIPE.replace('id = "r"', 'id = "b"'),
        "already used",
    ),
    "a short since": (HEAD + BUG.replace('since = "2.1.0"', 'since = "2.1"'), "since must be"),
    "versions that are no specifier": (
        HEAD + BUG.replace('versions = "<2.1.0"', 'versions = "soon"'),
        "PEP 440",
    ),
    "empty versions": (HEAD + BUG.replace('versions = "<2.1.0"', 'versions = ""'), "PEP 440"),
    "a bug without a quantity": (
        HEAD + BUG.replace('["metrics"]', "[]"),
        "quantities is empty",
    ),
    "a repeated quantity": (
        HEAD + BUG.replace('["metrics"]', '["metrics", "metrics"]'),
        "repeats a token",
    ),
    "a commit that is no sha": (HEAD + BUG + 'commit = "HEAD"\n', "hex sha"),
    "an unknown effect": (HEAD + RECIPE.replace('"refusal"', '"mood"'), "effect must be one of"),
    "a numbers recipe without a quantity": (
        HEAD + RECIPE.replace('"refusal"', '"numbers"'),
        "quantities is empty",
    ),
    "a default whose since is not its edition": (
        HEAD + DEFAULT.replace('since = "2.1.0"', 'since = "2.1.1"'),
        "has since '2.1.0'",
    ),
    "a default with a bad edition": (
        HEAD + DEFAULT.replace('edition = "2.1"', 'edition = "2"'),
        "edition must be a minor version",
    ),
    "a default that moves nothing": (
        HEAD + DEFAULT.replace("new = 0.45", "new = 0.5"),
        "old and new are the same value",
    ),
    "a default that is a table": (
        HEAD + DEFAULT.replace("old = 0.5", "old = { a = 1 }"),
        "not tables",
    ),
    "a migration with two shapes": (
        HEAD + MOVE + 'instead = "x"\n',
        "exactly one shape",
    ),
    "a migration with no shape": (
        HEAD + '[[migration]]\ndocument = "config"\nsince = "2.1.0"\n',
        "exactly one shape",
    ),
    "sealed on a move": (HEAD + MOVE + 'sealed = "drop"\n', "sealed only takes 'drop'"),
    "sealed that is not drop": (
        HEAD
        + '[[migration]]\ndocument = "config"\nold = "a.b"\ninstead = "x"\nsealed = "keep"\n'
        + 'since = "2.1.0"\n',
        "sealed only takes 'drop'",
    ),
    "a rule that is a module path": (
        HEAD + MOVE + 'rule = "hydromodpy.config.config_migration.f"\n',
        "rule must be a name",
    ),
    "a rule with a leading underscore": (HEAD + MOVE + 'rule = "_f"\n', "rule must be a name"),
    "a bad document": (HEAD + MOVE.replace('"config"', '"Config"'), "document must match"),
    "a path that is no dotted path": (HEAD + MOVE.replace('"a.c"', '"a..c"'), "dotted path"),
    "a move to itself": (HEAD + MOVE.replace('"a.c"', '"a.b"'), "same path"),
    "an empty instead": (
        HEAD + '[[migration]]\ndocument = "config"\nold = "a.b"\ninstead = " "\nsince = "2.1.0"\n',
        "instead must be",
    ),
    "a value renamed to itself": (
        HEAD
        + '[[migration]]\ndocument = "config"\nkey = "a.b"\nold_value = "x"\nnew_value = "x"\n'
        + 'since = "2.1.0"\n',
        "same value",
    ),
    "a value that is a table": (
        HEAD
        + '[[migration]]\ndocument = "config"\nkey = "a.b"\nold_value = { x = 1 }\n'
        + 'new_value = "x"\nsince = "2.1.0"\n',
        "string, a number or a boolean",
    ),
    "the same row twice": (HEAD + MOVE + MOVE.replace('"a.c"', '"a.d"'), "same row as"),
    "a text that does not parse": ("schema = ", "cannot be read"),
}


@pytest.mark.parametrize(("text", "fault"), FAULTS.values(), ids=FAULTS.keys())
def test_a_faulty_register_is_refused_with_its_fault(text: str, fault: str) -> None:
    with pytest.raises(ValueError, match=fault):
        read(text)


def test_every_fault_is_told_at_once() -> None:
    text = HEAD + BUG.replace('id = "b"', 'id = "B"') + MOVE + 'rule = "_f"\n'

    with pytest.raises(ValueError, match=r"2 fault\(s\)"):
        read(text)


HITS = (
    ("a version in the set, a quantity it touches", "2.0.0", ("metrics",), True),
    ("a pre-release in the set", "2.0.0rc1", ("metrics",), True),
    ("a pre-release of the fix, which PEP 440 leaves out", "2.1.0rc1", ("metrics",), False),
    ("the version of the fix", "2.1.0", ("metrics",), False),
    ("another quantity", "2.0.0", ("heads@modflow6",), False),
    ("one quantity of several", "2.0.0", ("heads@modflow6", "metrics"), True),
)


@pytest.mark.parametrize(
    ("case", "version", "quantities", "hit"), HITS, ids=[row[0] for row in HITS]
)
def test_a_bug_hits_a_run_of_its_versions_that_exposes_its_quantities(
    case: str, version: str, quantities: tuple[str, ...], hit: bool
) -> None:
    del case
    bug = Bug(id="b", since="2.1.0", versions="<2.1.0", quantities=("metrics",), text="t")

    assert bug.hits(version, quantities) is hit


DELAYS = (
    ("2.3.0", "2.4.9", False),
    ("2.3.0", "2.5.0a1", True),
    ("2.3.0", "2.5.0", True),
    ("2.3.0", "3.0.0", True),
    ("2.0.0", "2.1.0rc1", False),
    ("2.0.0", "2.1.0", False),
    ("2.0.0", "2.2.0", True),
    ("2.1.0", "2.2.5", False),
)


@pytest.mark.parametrize(("since", "version", "late"), DELAYS)
def test_the_delay_is_two_minor_versions_the_one_that_retired_the_form_included(
    since: str, version: str, late: bool
) -> None:
    assert DELAY_MINORS == 2
    assert outlived(since, version) is late


@pytest.mark.parametrize(("since", "removal"), [("2.3.0", "2.5.0"), ("2.0.0", "2.2.0")])
def test_a_form_leaves_two_minor_versions_after_its_since(since: str, removal: str) -> None:
    assert removal_of(since) == removal


def test_a_version_that_does_not_parse_is_refused() -> None:
    with pytest.raises(ValueError, match="is not a version"):
        outlived("2.0.0", "two")


def test_the_editions_are_the_first_one_and_each_edition_of_a_default() -> None:
    register = read(
        HEAD
        + DEFAULT
        + DEFAULT.replace('id = "d"', 'id = "e"').replace('key = "solver.x"', 'key = "solver.y"')
        + DEFAULT.replace('id = "d"', 'id = "f"')
        .replace('"2.1"', '"2.10"')
        .replace('"2.1.0"', '"2.10.0"')
    )

    assert editions(register) == (FIRST_EDITION, "2.1", "2.10")
    assert editions(read(HEAD)) == ("2.0",)


def test_the_rows_of_one_document_come_in_the_order_of_the_file() -> None:
    register = read(
        HEAD
        + MOVE
        + MOVE.replace('"config"', '"sidecar"')
        + MOVE.replace('"a.b"', '"z.y"').replace('"a.c"', '"z.x"')
    )

    assert [row.old for row in migrations_of("config", register)] == ["a.b", "z.y"]
    assert [row.old for row in migrations_of("sidecar", register)] == ["a.b"]


SHAPES = (
    (Migration(document="config", since="2.1.0", old="a", new="b"), "move"),
    (Migration(document="config", since="2.1.0", old="a", instead="x"), "retire"),
    (Migration(document="config", since="2.1.0", key="a", old_value=1, new_value=2), "value"),
)


@pytest.mark.parametrize(("row", "shape"), SHAPES, ids=[row[1] for row in SHAPES])
def test_a_migration_row_has_one_shape(row: Migration, shape: str) -> None:
    assert row.shape == shape


def test_the_refusal_of_a_pre_release_form_names_every_key_and_the_way_out() -> None:
    told = prerelease_refusal("project.toml", ["flow.active_bc", "calibration.max_iter"])

    assert told.startswith("project.toml holds flow.active_bc, calibration.max_iter, written by")
    assert 'pip install "hydromodpy~=2.0.0"' in told
    assert "hmp doctor --fix-config" in told


def test_a_refusal_with_no_file_to_rewrite_does_not_promise_the_doctor() -> None:
    told = prerelease_refusal("--set", ["flow.active_bc"], rewritable=False)

    assert "a pre-release of 2.0" in told
    assert "hmp doctor" not in told
