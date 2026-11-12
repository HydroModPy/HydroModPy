"""The register of changes is read once, checked row by row, and holds the delay of an old form."""

from __future__ import annotations

import pytest

from hydromodpy.schema.changes import REGISTER, Migration, outlived, read

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
    ("the first pre-release in the set, a quantity it touches", "2.0.0a1", ("metrics",), True),
    ("the last pre-release in the set", "2.0.0rc1", ("metrics",), True),
    ("a dev version before the first pre-release", "2.0.0.dev0", ("metrics",), False),
    ("the dev version after the last pre-release", "2.0.0rc2.dev0", ("metrics",), False),
    ("the version of the fix", "2.0.0", ("metrics",), False),
    ("another quantity", "2.0.0a5", ("heads@modflow6",), False),
    ("one quantity of several", "2.0.0a5", ("heads@modflow6", "metrics"), True),
)


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


def test_a_version_that_does_not_parse_is_refused() -> None:
    with pytest.raises(ValueError, match="is not a version"):
        outlived("2.0.0", "two")


SHAPES = (
    (Migration(document="config", since="2.1.0", old="a", new="b"), "move"),
    (Migration(document="config", since="2.1.0", old="a", instead="x"), "retire"),
    (Migration(document="config", since="2.1.0", key="a", old_value=1, new_value=2), "value"),
)
