from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def test_load_toml_with_base_config_merges_nested_sections(tmp_path: Path) -> None:
    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                "",
                "[geographic]",
                "",
                "[site]",
                'name = "site_a"',
                "",
                "[geographic.catchment]",
                'kind = "dem"',
                "[[data.dem.sources]]",
                'source = "file"',
                'path = "inputs/dem.tif"',
                "[flow.bc.ocean]",
                'kind = "dirichlet"',
                'value = "1.0 m"',
                "data_value = true",
            ]
        ),
        encoding="utf-8",
    )
    child_path.write_text(
        "\n".join(
            [
                'base_config = "base.toml"',
                "",
                "[flow.bc.drainage]",
                'kind = "drain"',
                'value = "0.0 m2/s"',
                'application_domain = "top"',
            ]
        ),
        encoding="utf-8",
    )

    payload = load_toml_with_base_config(child_path, root=ROOT_CONFIG)

    assert payload["geographic"]["catchment"]["kind"] == "dem"
    assert list(payload["flow"]["bc"]) == ["ocean", "drainage"]
    assert payload["flow"]["bc"]["ocean"]["data_value"] is True
    assert payload["flow"]["bc"]["drainage"]["application_domain"] == "top"


def test_hydromodpy_config_from_toml_supports_base_config(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                "",
                "[site]",
                'name = "site_a"',
                "",
                "[geographic.catchment]",
                'kind = "dem"',
                "[[data.dem.sources]]",
                'source = "file"',
                'path = "dem.tif"',
                "[flow.bc.ocean]",
                'kind = "dirichlet"',
                'value = "1.0 m"',
                "data_value = true",
            ]
        ),
        encoding="utf-8",
    )
    child_path.write_text(
        "\n".join(
            [
                'base_config = "base.toml"',
                "",
                "[flow.bc.drainage]",
                'kind = "drain"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(child_path)

    assert cfg.workspace.project_root == tmp_path.resolve()
    assert str(cfg.data.dem.sources[0].path) == str(dem_path.resolve())
    assert cfg.flow.active_bc == ["ocean", "drainage"]


def test_a_list_of_tables_of_the_same_length_replaces_the_inherited_list(
    tmp_path: Path,
) -> None:
    (tmp_path / "base.toml").write_text(
        '[[data.recharge.sources]]\nsource = "file"\npath = "recharge"\nstation_ids = ["A"]\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n[[data.recharge.sources]]\nstation_ids = ["B"]\n',
        encoding="utf-8",
    )

    payload = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert payload["data"]["recharge"]["sources"] == [{"station_ids": ["B"]}]


def test_merge_of_lists_follows_one_rule_whatever_the_lengths() -> None:
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    base = {"export": [{"variables": "head", "time": "last"}, {"variables": "budget"}]}

    same_length = merge_toml_payloads(base, {"export": [{"variables": "a"}, {"variables": "b"}]})
    other_length = merge_toml_payloads(base, {"export": [{"variables": "a"}]})
    appended = merge_toml_payloads(base, {"export__append": [{"variables": "c"}]})
    deleted = merge_toml_payloads(base, {"export__delete": True})

    assert same_length["export"] == [{"variables": "a"}, {"variables": "b"}]
    assert other_length["export"] == [{"variables": "a"}]
    assert appended["export"] == [*base["export"], {"variables": "c"}]
    assert "export" not in deleted


@pytest.mark.parametrize("identity", ["id", "name", "source"])
def test_merge_directive_pairs_tables_by_identity_wherever_they_sit(identity: str) -> None:
    """A table inserted at the head of the base leaves the overlay on the table it names."""
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    base = {
        "x": [
            {identity: "head", "label": "H"},
            {identity: "a", "label": "A"},
            {identity: "b", "label": "B"},
        ]
    }

    merged = merge_toml_payloads(base, {"x__merge": [{identity: "b", "label": "B2"}]})

    assert merged["x"] == [base["x"][0], base["x"][1], {identity: "b", "label": "B2"}]


def test_merge_directive_uses_the_first_identity_every_table_holds() -> None:
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    base = {"x": [{"name": "n1", "source": "s1", "v": 1}, {"name": "n2", "source": "s2", "v": 2}]}

    named = merge_toml_payloads(base, {"x__merge": [{"name": "n2", "v": 3}]})
    sourced = merge_toml_payloads(base, {"x__merge": [{"source": "s2", "v": 4}]})

    assert named["x"][1]["v"] == 3
    assert sourced["x"][1]["v"] == 4


def test_merge_directive_pairs_one_table_with_one_table_without_an_identity() -> None:
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    merged = merge_toml_payloads({"x": [{"a": 1, "b": 2}]}, {"x__merge": [{"b": 3}]})

    assert merged["x"] == [{"a": 1, "b": 3}]


@pytest.mark.parametrize(
    ("base", "overlay", "message"),
    [
        pytest.param(
            {"x": [{"a": 1}, {"a": 2}]},
            {"x__merge": [{"a": 3}, {"a": 4}]},
            "needs one of id, name or source",
            id="same length, no identity",
        ),
        pytest.param(
            {"x": [{"id": "a"}, {"id": "b"}]},
            {"x__merge": [{"label": "A"}]},
            "needs one of id, name or source",
            id="identity on one side",
        ),
        pytest.param(
            {"x": [{"id": "a"}]},
            {"x__merge": [{"id": "z"}]},
            "no inherited table has id = 'z'",
            id="unknown",
        ),
        pytest.param(
            {"x": [{"id": "a"}, {"id": "a"}]},
            {"x__merge": [{"id": "a"}]},
            "the inherited tables cannot be told apart",
            id="twice in the base",
        ),
        pytest.param(
            {"x": [{"id": "a"}]},
            {"x__merge": [{"id": "a"}, {"id": "a"}]},
            "the written tables cannot be told apart",
            id="twice in the overlay",
        ),
        pytest.param({}, {"x__merge": [{"a": 2}]}, "no inherited list", id="missing"),
        pytest.param({"x": [1]}, {"x__merge": [{"a": 2}]}, "inherited list of tables", id="values"),
        pytest.param({"x": [{"a": 1}]}, {"x__merge": [1]}, "requires a list of tables", id="items"),
        pytest.param(
            {"x": [{"a": 1}]},
            {"x": [{"a": 2}], "x__merge": [{"a": 3}]},
            "write only one of them",
            id="both",
        ),
    ],
)
def test_merge_directive_refuses_what_it_cannot_pair(
    base: dict, overlay: dict, message: str
) -> None:
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    with pytest.raises(ValueError, match=re.escape(message)):
        merge_toml_payloads(base, overlay)


def _tables_of_the_schema() -> tuple[dict[str, type], set[str]]:
    """Walk the root model: each list of tables by path, and every field name met."""
    from pydantic import BaseModel

    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config_kit.introspect import iter_basemodels

    lists: dict[str, type] = {}
    names: set[str] = set()
    seen: set[type] = set()

    def walk(model: type[BaseModel], path: str) -> None:
        if model in seen:
            return
        seen.add(model)
        for name, info in model.model_fields.items():
            names.add(name)
            here = f"{path}.{name}" if path else name
            for nested in iter_basemodels(info.annotation):
                if _holds_a_list(info.annotation):
                    lists.setdefault(here, nested)
                walk(nested, here)

    walk(HydroModPyConfig, "")
    return lists, names


def _holds_a_list(annotation: object) -> bool:
    from typing import get_args, get_origin

    origin = get_origin(annotation)
    return origin is list or any(
        _holds_a_list(arg) for arg in get_args(annotation) if arg is not ...
    )


def test_no_field_of_the_schema_collides_with_a_directive() -> None:
    _, names = _tables_of_the_schema()

    assert len(names) > 500
    assert not [name for name in names if "__" in name]


def test_the_identity_of_each_list_of_tables_is_the_one_the_merge_reads() -> None:
    """A new list of tables comes through here, so its author says how ``__merge`` pairs it."""
    from hydromodpy.core.toml_io.merge import IDENTITY_KEYS

    lists, _ = _tables_of_the_schema()
    by_identity: dict[str | None, set[str]] = {}
    for path, model in lists.items():
        key = next((key for key in IDENTITY_KEYS if key in model.model_fields), None)
        by_identity.setdefault(key, set()).add(path)

    assert by_identity.pop("id") == {"observation.points", "simulation.process"}
    assert {"calibration.phases", "calibration.objective_blocks", "domain.layers.layer"} <= (
        by_identity.pop("name")
    )
    assert all(path.endswith(".sources") for path in by_identity.pop("source"))
    assert {"export", "mesh.refinement_zone", "sites.export"} <= by_identity.pop(None)
    assert not by_identity


@pytest.mark.parametrize(
    ("first", "second", "written", "expected"),
    [
        pytest.param(
            "[domain.layers]\nnlay = 3\n",
            "[modflow6.sgrid.vertical]\nnlay = 5\n",
            "chain",
            5,
            id="an old name in a child beats a new name in its parent",
        ),
        pytest.param(
            "[modflow6.sgrid.vertical]\nnlay = 3\n",
            "[domain.layers]\nnlay = 5\n",
            "chain",
            5,
            id="a new name in a child beats an old name in its parent",
        ),
        pytest.param(
            "[domain.layers]\nnlay = 3\n",
            "[modflow6.sgrid.vertical]\nnlay = 5\n",
            "overlay",
            5,
            id="an old name in an overlay beats a new name in the file",
        ),
        pytest.param(
            '[domain.layers]\nnlay = 3\n[[simulation.process]]\nid = "flow"\ntype = "flow"\n'
            'solvers = ["modflow6"]\n',
            "[modflownwt.sgrid.vertical]\nnlay = 5\n",
            "chain",
            5,
            id="the one old table of the chain moves whatever the solver",
        ),
    ],
)
def test_each_file_is_migrated_before_the_merge(
    tmp_path: Path, first: str, second: str, written: str, expected: int
) -> None:
    from argparse import Namespace

    from hydromodpy.cli.effective_toml import materialize_effective_toml
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    base = tmp_path / "base.toml"
    base.write_text(first, encoding="utf-8")
    other = tmp_path / "other.toml"
    with pytest.warns(ConfigKeyRenamedWarning):
        if written == "chain":
            other.write_text(f'base_config = "base.toml"\n{second}', encoding="utf-8")
            payload = load_toml_with_base_config(other, root=ROOT_CONFIG)
        else:
            other.write_text(second, encoding="utf-8")
            effective, payload, _ = materialize_effective_toml(
                base, args=Namespace(overlay=[other], set_overrides=[], case=None)
            )
            assert effective is not None
            effective.unlink()

    assert payload["domain"]["layers"]["nlay"] == expected
    assert "modflow6" not in payload
    assert "sgrid" not in payload.get("solver", {}).get("modflow6", {})


def test_a_set_and_a_variable_written_under_an_old_name_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from hydromodpy.cli.effective_toml import materialize_effective_toml
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    base = tmp_path / "base.toml"
    base.write_text("[domain.layers]\nnlay = 3\n", encoding="utf-8")
    args = Namespace(overlay=[], set_overrides=["modflow6.sgrid.vertical.nlay=5"], case=None)

    with pytest.warns(ConfigKeyRenamedWarning, match="--set: .*write the new name") as told:
        effective, payload, lineage = materialize_effective_toml(base, args=args)
    assert effective is not None
    effective.unlink()

    assert payload["domain"]["layers"]["nlay"] == 5
    assert lineage == {"domain.layers.nlay": 5}
    assert "fix-config" not in str(told[0].message)

    monkeypatch.setenv("HMP_SET_modflow6__sgrid__vertical__nlay", "7")
    with pytest.warns(ConfigKeyRenamedWarning, match=r"HMP_SET_\*"):
        effective, payload, lineage = materialize_effective_toml(
            base, args=Namespace(overlay=[], set_overrides=[], case=None)
        )
    assert effective is not None
    effective.unlink()
    assert payload["domain"]["layers"]["nlay"] == 7


@pytest.mark.parametrize(
    ("solver", "expected"),
    [pytest.param("modflow6", 3, id="MODFLOW 6"), pytest.param("modflow_nwt", 5, id="NWT")],
)
def test_the_table_of_the_flow_solver_wins_across_the_files(
    tmp_path: Path, solver: str, expected: int
) -> None:
    """A table a solver never read stays unread, even when a child writes it."""
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    (tmp_path / "base.toml").write_text(
        f'[solver]\nbackend = "{solver}"\n[modflow6.sgrid.vertical]\nnlay = 3\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n[modflownwt.sgrid.vertical]\nnlay = 5\n', encoding="utf-8"
    )

    with pytest.warns(ConfigKeyRenamedWarning):
        payload = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert payload["domain"]["layers"]["nlay"] == expected


def test_a_table_two_files_fill_key_by_key_waits_for_the_merge(tmp_path: Path) -> None:
    """Toggles of one ``[export]`` table in two files keep both, as they always did."""
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    (tmp_path / "base.toml").write_text(
        '[export]\nnetcdf = true\nvariables = ["head"]\n', encoding="utf-8"
    )
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n[export]\nvtu = true\n', encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning):
        payload = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert [block["format"] for block in payload["export"]] == ["netcdf", "vtu"]


def test_an_overlay_keeps_its_directives_until_it_meets_the_file(tmp_path: Path) -> None:
    """An overlay merged on nothing first would turn ``__append`` into a plain list."""
    from argparse import Namespace

    from hydromodpy.cli.effective_toml import materialize_effective_toml

    base = tmp_path / "base.toml"
    base.write_text(
        '[[export]]\nvariables = "head"\n[[simulation.process]]\nid = "flow"\nsolvers = ["a"]\n',
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.toml"
    overlay.write_text(
        '[[export__append]]\nvariables = "budget"\n'
        '[[simulation.process__merge]]\nid = "flow"\nsolvers = ["b"]\n',
        encoding="utf-8",
    )

    effective, payload, _ = materialize_effective_toml(
        base, args=Namespace(overlay=[overlay], set_overrides=[], case=None)
    )
    assert effective is not None
    effective.unlink()

    assert payload["export"] == [{"variables": "head"}, {"variables": "budget"}]
    assert payload["simulation"]["process"] == [{"id": "flow", "solvers": ["b"]}]
