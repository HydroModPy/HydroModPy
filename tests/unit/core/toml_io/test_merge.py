"""Merging TOML layers: tables merge key by key, lists replace, three suffixes adjust one key."""

from __future__ import annotations

import pytest

from hydromodpy.core.toml_io.merge import merge_toml_payloads


def test_a_table_merges_key_by_key_and_a_scalar_is_replaced() -> None:
    base = {"flow": {"k": 1.0, "ss": 1e-5}, "name": "a"}
    over = {"flow": {"k": 2.0}, "name": "b"}
    assert merge_toml_payloads(base, over) == {"flow": {"k": 2.0, "ss": 1e-5}, "name": "b"}


def test_a_list_in_the_overlay_replaces_the_inherited_list_whole() -> None:
    assert merge_toml_payloads({"p": ["A", "B"]}, {"p": ["C"]}) == {"p": ["C"]}


def test_the_inputs_are_left_untouched() -> None:
    base = {"flow": {"k": 1.0}}
    merge_toml_payloads(base, {"flow": {"k": 2.0}})
    assert base == {"flow": {"k": 1.0}}


def test_layers_apply_in_the_order_defaults_files_overlays_cli_env() -> None:
    merged = merge_toml_payloads(
        {"x": "defaults"},
        [{"x": "file1"}, {"x": "file2"}],
        overlays=[{"x": "overlay"}],
        cli_overrides={"x": "cli"},
        env_overrides={"x": "env"},
    )
    assert merged == {"x": "env"}
    only_files = merge_toml_payloads({"x": "d", "y": 1}, [{"x": "f"}], overlays=[{"z": 3}])
    assert only_files == {"x": "f", "y": 1, "z": 3}


def test_append_adds_after_the_inherited_items_or_creates_the_list() -> None:
    assert merge_toml_payloads({"p": ["A"]}, {"p__append": ["B"]}) == {"p": ["A", "B"]}
    assert merge_toml_payloads({}, {"p__append": ["B"]}) == {"p": ["B"]}


def test_delete_removes_an_inherited_key() -> None:
    assert merge_toml_payloads({"a": 1, "mesh": {"n": 2}}, {"mesh__delete": True}) == {"a": 1}


def test_a_directive_inside_a_table_the_base_lacks_is_applied_and_stripped() -> None:
    merged = merge_toml_payloads({}, {"flow": {"p__append": ["x"]}})
    assert merged == {"flow": {"p": ["x"]}}


def test_merge_pairs_tables_by_identity_and_keeps_the_ones_not_named() -> None:
    base = {"s": [{"id": "a", "v": 1, "w": 1}, {"id": "b", "v": 2, "w": 2}]}
    over = {"s__merge": [{"id": "b", "v": 20}]}
    assert merge_toml_payloads(base, over) == {
        "s": [{"id": "a", "v": 1, "w": 1}, {"id": "b", "v": 20, "w": 2}]
    }


def test_merge_falls_back_to_the_next_identity_key_every_table_holds() -> None:
    base = {"s": [{"name": "a", "v": 1}, {"name": "b", "v": 2}]}
    merged = merge_toml_payloads(base, {"s__merge": [{"name": "a", "v": 9}]})
    assert merged["s"][0]["v"] == 9


def test_merge_of_one_table_with_one_table_needs_no_identity() -> None:
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
def test_a_wrong_directive_is_refused_with_the_reason(base, over, message) -> None:
    with pytest.raises(ValueError, match=message):
        merge_toml_payloads(base, over)
