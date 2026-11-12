from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig


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


OLD_MF6 = "[modflow6.process_specific]\nvka = {}\n"
NEW_MF6 = "[solver.modflow6.process_specific]\nvka = {}\n"
OLD_NWT = "[modflownwt.process_specific]\nvka = {}\n"
NEW_NWT = "[solver.modflow_nwt.process_specific]\nvka = {}\n"


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
