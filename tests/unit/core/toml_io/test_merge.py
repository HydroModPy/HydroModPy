"""Merging TOML layers: tables merge key by key, lists replace, three suffixes adjust one key.

A graph of files merges by one rule: the most derived writer of a key wins, and
two writers that do not inherit each other must agree. The graph of the tables
below is a diamond, ``R`` inheriting the site ``S`` and the experiment ``E``,
both inheriting the model ``M``.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.toml_io.merge import (
    BaseConfigConflict,
    ancestors_of,
    merge_graph,
    merge_toml_payloads,
)


def test_append() -> None:
    assert merge_toml_payloads({"p": ["A"]}, {"p__append": ["B"]}) == {"p": ["A", "B"]}
    assert merge_toml_payloads({}, {"p__append": ["B"]}) == {"p": ["B"]}


def test_a_directive_in_a_new_table_is_applied() -> None:
    merged = merge_toml_payloads({}, {"flow": {"p__append": ["x"]}})
    assert merged == {"flow": {"p": ["x"]}}


def test_merge_pairs_tables_by_identity() -> None:
    base = {"s": [{"id": "a", "v": 1, "w": 1}, {"id": "b", "v": 2, "w": 2}]}
    over = {"s__merge": [{"id": "b", "v": 20}]}
    assert merge_toml_payloads(base, over) == {
        "s": [{"id": "a", "v": 1, "w": 1}, {"id": "b", "v": 20, "w": 2}]
    }


def test_merge_falls_back_to_the_next_identity_key() -> None:
    base = {"s": [{"name": "a", "v": 1}, {"name": "b", "v": 2}]}
    merged = merge_toml_payloads(base, {"s__merge": [{"name": "a", "v": 9}]})
    assert merged["s"][0]["v"] == 9


def test_merge_of_a_single_table() -> None:
    merged = merge_toml_payloads({"s": [{"v": 1, "w": 2}]}, {"s__merge": [{"v": 5}]})
    assert merged == {"s": [{"v": 5, "w": 2}]}


_MERGE_BASE = {"s": [{"id": "a", "v": 1}, {"id": "b", "v": 2}]}

_REFUSED: list[tuple[str, dict, dict, str]] = [
    ("empty merge target", {}, {"__merge": []}, "empty target key for merge"),
    ("merge not a list", {}, {"s__merge": 3}, "requires a list of tables"),
    ("merge of scalars", {}, {"s__merge": [1]}, "requires a list of tables"),
    ("empty append target", {}, {"__append": []}, "empty target key for append"),
    ("append not a list", {}, {"s__append": "x"}, "requires a list value, got str"),
    ("empty delete target", {}, {"__delete": True}, "empty target key for delete"),
    ("delete not true", {}, {"s__delete": 1}, "literal boolean true"),
    ("both set", {}, {"s": [], "s__merge": []}, "both set"),
    ("no inherited list", {}, {"s__merge": [{"id": 1}]}, "no inherited list"),
    ("inherited not a list", {"s": 3}, {"s__merge": [{"id": 1}]}, "needs an inherited list"),
    (
        "no identity",
        {"s": [{"v": 1}, {"v": 2}]},
        {"s__merge": [{"v": 1}]},
        "cannot pair these tables",
    ),
    (
        "duplicate identity",
        {"s": [{"id": "a"}, {"id": "a"}]},
        {"s__merge": [{"id": "a"}]},
        "cannot be told apart",
    ),
    (
        "unknown identity",
        _MERGE_BASE,
        {"s__merge": [{"id": "zzz"}]},
        "no inherited table has id = 'zzz'",
    ),
    ("append to a scalar", {"s": 3}, {"s__append": [1]}, "cannot append to non-list"),
]


@pytest.mark.parametrize(
    ("base", "over", "message"),
    [pytest.param(b, o, m, id=i) for i, b, o, m in _REFUSED],
)
def test_refusals(base, over, message) -> None:
    with pytest.raises(ValueError, match=message):
        merge_toml_payloads(base, over)


def _diamond(m: dict, s: dict, e: dict, r: dict | None = None) -> tuple[dict, dict]:
    """Merge the model, the site, the experiment and the run that inherits both."""
    nodes = [("M", m, ()), ("S", s, ("M",)), ("E", e, ("M",)), ("R", r or {}, ("S", "E"))]
    return merge_graph(nodes)


MODEL = {"flow": {"K": 1.0, "Sy": 0.1}, "figures": ["map"]}

_GRAPH = [
    # (id, site, experiment, run, merged document, origins checked)
    ("a file overrides what it inherits", {"site": "n"}, {"flow": {"K": 5.0}}, {},
     {"flow": {"K": 5.0, "Sy": 0.1}, "figures": ["map"], "site": "n"},
     {"flow.K": ("E",), "flow.Sy": ("M",), "site": ("S",)}),
    ("two branches agree", {"flow": {"K": 5.0}}, {"flow": {"K": 5.0}}, {},
     {"flow": {"K": 5.0, "Sy": 0.1}, "figures": ["map"]}, {"flow.K": ("S", "E")}),
    ("the run settles a disagreement", {"flow": {"K": 3.0}}, {"flow": {"K": 5.0}},
     {"flow": {"K": 7.0}}, {"flow": {"K": 7.0, "Sy": 0.1}, "figures": ["map"]},
     {"flow.K": ("R",)}),
    ("appends of two branches add up", {"figures__append": ["site"]},
     {"figures__append": ["root"]}, {},
     {"flow": {"K": 1.0, "Sy": 0.1}, "figures": ["map", "site", "root"]},
     {"figures": ("M", "S", "E")}),
    ("a branch replaces, the other adds", {"figures__append": ["site"]},
     {"figures": ["root"]}, {},
     {"flow": {"K": 1.0, "Sy": 0.1}, "figures": ["root", "site"]}, {"figures": ("E", "S")}),
    ("a branch removes an inherited key", {}, {"flow": {"Sy__delete": True}}, {},
     {"flow": {"K": 1.0}, "figures": ["map"]}, {}),
    ("a table written fresh drops what it inherits", {},
     {"flow__delete": True, "flow": {"K": 9.0}}, {},
     {"flow": {"K": 9.0}, "figures": ["map"]}, {"flow.K": ("E",)}),
]  # fmt: skip


@pytest.mark.parametrize(
    ("site", "experiment", "run", "merged", "origins"),
    [pytest.param(*case, id=name) for name, *case in _GRAPH],
)
def test_the_most_derived_writer_of_a_key_wins(site, experiment, run, merged, origins) -> None:
    document, found = _diamond(MODEL, site, experiment, run)

    assert document == merged
    assert {key: found[key] for key in origins} == origins


_GRAPH_REFUSED = [
    ("two values", {"flow": {"K": 3.0}}, {"flow": {"K": 5.0}},
     r"flow.K is written by S \(3.0\) and by E \(5.0\), and neither file inherits"),
    ("two lists", {"figures": ["a"]}, {"figures": ["b"]}, "figures is written by S"),
    ("a value and a removal", {"flow": {"K": 3.0}}, {"flow": {"K__delete": True}},
     r"by E \(removed\)"),
    ("a table and a value", {"flow": {"K": {"x": 1}}}, {"flow": {"K": 2.0}},
     r"S \(a table\) and by E \(2.0\)"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("site", "experiment", "message"),
    [pytest.param(*case, id=name) for name, *case in _GRAPH_REFUSED],
)
def test_two_branches_that_disagree_are_refused(site, experiment, message) -> None:
    with pytest.raises(BaseConfigConflict, match=message):
        _diamond(MODEL, site, experiment)


def test_a_merge_directive_reads_what_its_file_inherits() -> None:
    model = {"s": [{"name": "a", "v": 1}, {"name": "b", "v": 1}]}
    document, _ = _diamond(model, {}, {"s__merge": [{"name": "b", "v": 2}]})

    assert document == {"s": [{"name": "a", "v": 1}, {"name": "b", "v": 2}]}


CHAIN = [
    {"t": {"a": 1, "b": 2}, "l": ["x"], "gone": 1, "u": {"v": 1}},
    {"t": {"a__delete": True, "a": 3}, "l__append": ["y"], "gone__delete": True},
    {"t": {"c": 4}, "l": ["z"], "u__delete": True, "u": {"w": 2}},
    {"l__append": ["q"], "gone": 5},
]
"""A chain of single bases: each file inherits the one before."""


def test_a_chain_merges_as_the_files_one_after_the_other() -> None:
    nodes = [(i, own, (i - 1,) if i else ()) for i, own in enumerate(CHAIN)]
    expected: dict = {}
    for own in CHAIN:
        expected = merge_toml_payloads(expected, own)

    document, _ = merge_graph(nodes)

    assert document == expected
    assert list(document) == list(expected) and list(document["t"]) == list(expected["t"])


def test_the_ancestors_of_a_file_are_every_file_it_inherits() -> None:
    above = ancestors_of({"M": (), "S": ("M",), "E": ("M",), "R": ("S", "E")})

    assert above["R"] == {"S", "E", "M"} and above["S"] == {"M"} and above["M"] == frozenset()
