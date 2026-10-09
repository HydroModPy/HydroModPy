from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def test_load_toml_with_base_config_merges_nested_sections(tmp_path: Path) -> None:
    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "[flow]",
                'active_bc = ["ocean"]',
                "",
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
                "[flow]",
                'active_bc = ["ocean", "drainage"]',
                "",
                "[flow.bc.drainage]",
                'kind = "cauchy"',
                'value = "0.0 m2/s"',
                'application_domain = "top"',
            ]
        ),
        encoding="utf-8",
    )

    payload = load_toml_with_base_config(child_path)

    assert payload["workspace"]["project_root"] == str(tmp_path / "demo")
    assert payload["flow"]["active_bc"] == ["ocean", "drainage"]
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
                f'project_root = "{tmp_path / "demo"}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "[flow]",
                'active_bc = ["ocean"]',
                "",
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
                "[flow]",
                'active_bc = ["ocean", "drainage"]',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(child_path)

    assert cfg.workspace.catch_name == "demo"
    assert str(cfg.geographic.dem_init_path) == str(dem_path.resolve())
    assert cfg.flow.active_bc == ["ocean", "drainage"]


def test_a_list_of_tables_of_the_same_length_replaces_the_inherited_list(
    tmp_path: Path,
) -> None:
    (tmp_path / "base.toml").write_text(
        '[[data.recharge.sources]]\nsource = "custom"\npath = "recharge"\nstation_ids = ["A"]\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n[[data.recharge.sources]]\nstation_ids = ["B"]\n',
        encoding="utf-8",
    )

    payload = load_toml_with_base_config(child)

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


def test_merge_directive_merges_tables_in_order() -> None:
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    base = {"simulation": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}

    merged = merge_toml_payloads(base, {"simulation__merge": [{"label": "A2"}, {}]})

    assert merged["simulation"] == [{"id": "a", "label": "A2"}, {"id": "b", "label": "B"}]


@pytest.mark.parametrize(
    ("base", "overlay", "message"),
    [
        pytest.param(
            {"x": [{"a": 1}]},
            {"x__merge": [{"a": 2}, {"a": 3}]},
            "has 2 table(s) and the inherited list has 1",
            id="length",
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
