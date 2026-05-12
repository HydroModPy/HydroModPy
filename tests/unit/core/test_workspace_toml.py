"""``workspace.toml`` template generator tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

from hydromodpy.core.state.paths import WORKSPACE_TOML_FILENAME
from hydromodpy.core.workspace.workspace_toml import (
    DEFAULT_WORKSPACE_TOML_TEMPLATE,
    render_workspace_toml,
    write_workspace_toml,
)


def test_template_contains_required_sections():
    rendered = render_workspace_toml(
        project_name="ws",
        creator_name="Bastien",
        creator_email="b@example.com",
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert "[workspace]" in rendered
    assert "[workspace.geographic_scope]" in rendered
    assert "[workspace.team]" in rendered
    assert "[workspace.tags]" in rendered


def test_render_outputs_valid_toml():
    rendered = render_workspace_toml(
        project_name="my_lab",
        creator_name="Alice",
        creator_email="alice@example.com",
        created_at="2026-05-12T00:00:00+00:00",
    )
    parsed = tomllib.loads(rendered)
    assert parsed["workspace"]["name"] == "my_lab"
    assert parsed["workspace"]["contact"] == "alice@example.com"
    assert "Alice" in parsed["workspace"]["team"]["members"]


def test_write_workspace_toml_idempotent(tmp_path: Path):
    target_dir = tmp_path / "ws"
    first = write_workspace_toml(
        target_dir,
        project_name="ws",
        creator_name="Bastien",
        creator_email="b@example.com",
    )
    assert first.name == WORKSPACE_TOML_FILENAME
    first_content = first.read_text(encoding="utf-8")

    second = write_workspace_toml(
        target_dir,
        project_name="overridden",
        creator_name="X",
        creator_email="x@example.com",
    )
    assert second == first
    assert second.read_text(encoding="utf-8") == first_content


def test_write_workspace_toml_force_overwrites(tmp_path: Path):
    target_dir = tmp_path / "ws"
    write_workspace_toml(
        target_dir,
        project_name="a",
        creator_name="A",
        creator_email="a@example.com",
    )
    second = write_workspace_toml(
        target_dir,
        project_name="b",
        creator_name="B",
        creator_email="b@example.com",
        force=True,
    )
    content = second.read_text(encoding="utf-8")
    assert 'name = "b"' in content
    assert 'contact = "b@example.com"' in content


def test_template_constant_is_exported():
    assert "[workspace]" in DEFAULT_WORKSPACE_TOML_TEMPLATE
    assert "{project_name}" in DEFAULT_WORKSPACE_TOML_TEMPLATE
