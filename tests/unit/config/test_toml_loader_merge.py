from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
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


OLD_MF6 = "[modflow6.process_specific]\nvka = {}\n"
NEW_MF6 = "[solver.modflow6.process_specific]\nvka = {}\n"
OLD_NWT = "[modflownwt.process_specific]\nvka = {}\n"
NEW_NWT = "[solver.modflow_nwt.process_specific]\nvka = {}\n"


@pytest.mark.parametrize(
    ("first", "second", "written", "solver", "expected"),
    [
        pytest.param(
            NEW_MF6.format(3.0),
            OLD_MF6.format(5.0),
            "chain",
            "modflow6",
            5.0,
            id="an old name in a child beats a new name in its parent",
        ),
        pytest.param(
            OLD_MF6.format(3.0),
            NEW_MF6.format(5.0),
            "chain",
            "modflow6",
            5.0,
            id="a new name in a child beats an old name in its parent",
        ),
        pytest.param(
            NEW_MF6.format(3.0),
            OLD_MF6.format(5.0),
            "overlay",
            "modflow6",
            5.0,
            id="an old name in an overlay beats a new name in the file",
        ),
        pytest.param(
            NEW_NWT.format(3.0) + '[[simulation.process]]\nid = "flow"\nkind = "flow"\n'
            'solvers = ["modflow6"]\n',
            OLD_NWT.format(5.0),
            "chain",
            "modflow_nwt",
            5.0,
            id="the old table of a solver that does not run moves to its own table",
        ),
    ],
)
def test_each_file_is_migrated_before_the_merge(
    tmp_path: Path, first: str, second: str, written: str, solver: str, expected: float
) -> None:
    from hydromodpy.config.loading import read_document
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
            payload = read_document(base, overlays=[other], root=ROOT_CONFIG)

    assert payload["solver"][solver]["process_specific"]["vka"] == expected
    assert "modflow6" not in payload
    assert "modflownwt" not in payload


def test_a_set_and_a_variable_written_under_an_old_name_win(tmp_path: Path) -> None:
    from hydromodpy.config.loading import read_document
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
    from hydromodpy.core.toml_io.loader import merge_toml_layers, read_toml_chain
    from hydromodpy.core.toml_io.overrides import env_overrides
    from hydromodpy.project.request import request_of

    base = tmp_path / "base.toml"
    base.write_text(NEW_MF6.format(3.0), encoding="utf-8")
    changes = {"modflow6.process_specific.vka": 5.0}

    with pytest.warns(ConfigKeyRenamedWarning, match="--set: .*write the new name") as told:
        payload = read_document(base, changes=changes, root=ROOT_CONFIG)

    assert payload["solver"]["modflow6"]["process_specific"]["vka"] == 5.0
    assert request_of(base, set=changes).overrides() == {
        "solver.modflow6.process_specific.vka": 5.0
    }
    assert "fix-config" not in str(told[0].message)

    variables = {"HMP_SET_modflow6__process_specific__vka": "7.0"}
    with pytest.warns(ConfigKeyRenamedWarning, match=r"HMP_SET_\*"):
        payload = merge_toml_layers(
            [read_toml_chain(base, root=None)],
            root=ROOT_CONFIG,
            env_overrides=env_overrides(variables),
        )
    assert payload["solver"]["modflow6"]["process_specific"]["vka"] == 7.0


@pytest.mark.parametrize(
    ("solver", "table", "expected"),
    [
        pytest.param("modflow6", "modflow6", 3.0, id="MODFLOW 6"),
        pytest.param("modflow_nwt", "modflow_nwt", 5.0, id="NWT"),
    ],
)
def test_the_table_of_each_solver_moves_on_its_own_across_the_files(
    tmp_path: Path, solver: str, table: str, expected: float
) -> None:
    """A table a solver never reads stays beside the one it reads, even when a child writes it."""
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    (tmp_path / "base.toml").write_text(
        f'[solver]\nbackend = "{solver}"\n' + OLD_MF6.format(3.0), encoding="utf-8"
    )
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n' + OLD_NWT.format(5.0), encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning):
        payload = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert payload["solver"]["backend"] == solver
    assert payload["solver"]["modflow6"]["process_specific"]["vka"] == 3.0
    assert payload["solver"]["modflow_nwt"]["process_specific"]["vka"] == 5.0
    assert payload["solver"][table]["process_specific"]["vka"] == expected


def test_a_table_two_files_fill_key_by_key_waits_for_the_merge(tmp_path: Path) -> None:
    """One moved table in two files keeps the keys of both, as the merge of tables always did."""
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    (tmp_path / "base.toml").write_text(
        "[modflow6.process_specific]\nvka = 2.0\n", encoding="utf-8"
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n[modflow6.process_specific]\nevt_extinction_depth = 3.0\n',
        encoding="utf-8",
    )

    with pytest.warns(ConfigKeyRenamedWarning):
        payload = load_toml_with_base_config(child, root=ROOT_CONFIG)

    assert payload["solver"]["modflow6"]["process_specific"] == {
        "vka": 2.0,
        "evt_extinction_depth": 3.0,
    }


def test_an_overlay_keeps_its_directives_until_it_meets_the_file(tmp_path: Path) -> None:
    """An overlay merged on nothing first would turn ``__append`` into a plain list."""
    from hydromodpy.config.loading import read_document

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

    payload = read_document(base, overlays=[overlay], root=ROOT_CONFIG)

    assert payload["export"] == [{"variables": "head"}, {"variables": "budget"}]
    assert payload["simulation"]["process"] == [{"id": "flow", "solvers": ["b"]}]
