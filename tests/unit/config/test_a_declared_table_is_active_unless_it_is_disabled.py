"""A boundary, a sink or a source is active when its table is declared, unless it says so.

No list names what a run builds. ``FlowConfig.active_bc`` and
``FlowConfig.active_sinks_sources`` read the tables, and ``enabled = false`` keeps a
table in the file and builds nothing from it.
"""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig

WELL = {"flux": -0.01, "location": {"kind": "relative_xy", "x_rel": 0.5, "y_rel": 0.5}}
LAKE = {"bedleak": 1e-6, "initial_stage": "10 m"}

#: (table family, name, a declared table, the name the run lists for it)
TABLES = [
    ("bc", "drainage", {}, "drainage"),
    ("sinks_sources", "recharge", {}, "recharge"),
    ("sinks_sources", "etp", {}, "etp"),
    ("sinks_sources", "wells", {"W1": WELL}, "wells"),
    ("sinks_sources", "lakes", {"pond": LAKE}, "lake"),
    ("sinks_sources", "sfr", {"main": {}}, "sfr"),
]


def _config(family: str, name: str, table: dict) -> FlowConfig:
    return FlowConfig(**{family: {name: table}})


def _listed(cfg: FlowConfig) -> list[str]:
    return [*cfg.active_bc, *cfg.active_sinks_sources]


def _switched_off(name: str, table: dict) -> dict:
    """The same table with ``enabled = false``: on the table, or on each entry of a map."""
    if name in {"wells", "lakes", "sfr"}:
        return {key: {**entry, "enabled": False} for key, entry in table.items()}
    return {**table, "enabled": False}


@pytest.mark.parametrize(("family", "name", "table", "listed"), TABLES)
def test_a_declared_table_is_active(family: str, name: str, table: dict, listed: str) -> None:
    assert _listed(_config(family, name, table)) == [listed]


@pytest.mark.parametrize(("family", "name", "table", "listed"), TABLES)
def test_a_table_that_says_enabled_false_builds_nothing(
    family: str, name: str, table: dict, listed: str
) -> None:
    assert _listed(_config(family, name, _switched_off(name, table))) == []


def test_a_run_that_declares_nothing_lists_nothing() -> None:
    assert _listed(FlowConfig()) == []


@pytest.mark.parametrize("old", ["active_bc", "active_sinks_sources"])
def test_the_lists_are_no_longer_a_key(old: str) -> None:
    with pytest.raises(ValueError, match=f"'{old}' is not accepted any more"):
        FlowConfig(**{old: ["drainage"]})
