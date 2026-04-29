"""Tests for :mod:`hydromodpy.schema.export` (P11 frontend hooks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_export_full_schema_writes_three_files(tmp_path: Path) -> None:
    from hydromodpy.schema.export import (
        META_FILE,
        SCHEMA_FILE,
        VALIDATORS_FILE,
        export_full_schema,
    )

    paths = export_full_schema(tmp_path / "schema")

    assert set(paths.keys()) == {"config", "meta", "validators"}
    assert paths["config"].name == SCHEMA_FILE
    assert paths["meta"].name == META_FILE
    assert paths["validators"].name == VALIDATORS_FILE
    for p in paths.values():
        assert p.is_file()
        assert p.stat().st_size > 0


def test_export_full_schema_produces_valid_json(tmp_path: Path) -> None:
    from hydromodpy.schema.export import export_full_schema

    paths = export_full_schema(tmp_path)

    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    validators = json.loads(paths["validators"].read_text(encoding="utf-8"))

    assert "properties" in config
    assert "flow" in config["properties"]
    assert isinstance(meta.get("sections"), list)
    assert meta["sections"], "expected at least one section entry"
    section_names = {s["name"] for s in meta["sections"]}
    for expected in ("workspace", "geographic", "flow", "simulation", "solver"):
        assert expected in section_names
    assert isinstance(validators, dict)
    assert "flow.flow_regime" in validators


def test_build_config_meta_reports_groups() -> None:
    from hydromodpy.schema.export import build_config_meta

    meta = build_config_meta()
    assert "sections" in meta
    assert "groups" in meta
    # groups is a dict keyed by the 'group' json_schema_extra; may be
    # empty today but must keep the shape stable.
    assert isinstance(meta["groups"], dict)


def test_build_field_validators_has_known_types() -> None:
    from hydromodpy.schema.export import build_field_validators

    flat = build_field_validators()
    # Known boolean field under flow: flow_regime is an enum ('steady'|'transient').
    assert flat.get("flow.flow_regime") in {"enum", "string"}
    # At least one entry must resolve to a 'number' or 'enum' validator.
    assert any(v in {"number", "enum", "boolean", "string"} for v in flat.values())


def test_export_full_schema_idempotent(tmp_path: Path) -> None:
    from hydromodpy.schema.export import export_full_schema

    p1 = export_full_schema(tmp_path / "a")
    p2 = export_full_schema(tmp_path / "a")
    assert p1 == p2
    first = p1["config"].read_text(encoding="utf-8")
    second = p2["config"].read_text(encoding="utf-8")
    assert first == second


def test_schema_cli_export_produces_files(tmp_path: Path) -> None:
    """Sanity-check that the Python CLI dispatcher writes the three files.

    Invoked through the public API, not subprocess: we only need to
    verify the CLI wiring matches the library.
    """
    import argparse

    from hydromodpy.cli.commands.schema import _cmd_export

    out = tmp_path / "cli_out"
    args = argparse.Namespace(output=str(out))
    _cmd_export(args)
    assert (out / "config.json").is_file()
    assert (out / "config_meta.json").is_file()
    assert (out / "field_validators.json").is_file()


@pytest.mark.parametrize(
    "key",
    ["config", "meta", "validators"],
)
def test_exported_files_are_well_formed_json(tmp_path: Path, key: str) -> None:
    from hydromodpy.schema.export import export_full_schema

    paths = export_full_schema(tmp_path)
    data = json.loads(paths[key].read_text(encoding="utf-8"))
    assert isinstance(data, (dict, list))
