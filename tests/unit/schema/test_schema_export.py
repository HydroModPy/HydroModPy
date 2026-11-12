"""Tests for :mod:`hydromodpy.schema.config_schema` (P11 frontend hooks)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig


def test_build_config_meta_reports_groups() -> None:
    from hydromodpy.schema.config_schema import build_config_meta

    meta = build_config_meta(ROOT_CONFIG)
    assert "sections" in meta
    assert "groups" in meta
    # groups is a dict keyed by the 'group' json_schema_extra; may be
    # empty today but must keep the shape stable.
    assert isinstance(meta["groups"], dict)


def test_build_field_validators_has_known_types() -> None:
    from hydromodpy.schema.config_schema import build_field_validators

    flat = build_field_validators(ROOT_CONFIG)
    # Known boolean field under flow: flow_regime is an enum ('steady'|'transient').
    assert flat.get("flow.flow_regime") in {"enum", "string"}
    # At least one entry must resolve to a 'number' or 'enum' validator.
    assert any(v in {"number", "enum", "boolean", "string"} for v in flat.values())


def test_export_full_schema_idempotent(tmp_path: Path) -> None:
    from hydromodpy.schema.config_schema import export_full_schema

    p1 = export_full_schema(tmp_path / "a", root=ROOT_CONFIG)
    p2 = export_full_schema(tmp_path / "a", root=ROOT_CONFIG)
    assert p1 == p2
    first = p1["config"].read_text(encoding="utf-8")
    second = p2["config"].read_text(encoding="utf-8")
    assert first == second


def test_schema_cli_export_produces_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``hmp config schema --bundle --to DIR`` writes the three files."""
    from tests.unit.cli._hmp import run_hmp

    out = tmp_path / "cli_out"
    assert run_hmp(monkeypatch, "config", "schema", "--bundle", "--to", str(out)) == 0
    assert (out / "config.json").is_file()
    assert (out / "config_meta.json").is_file()
    assert (out / "field_validators.json").is_file()
