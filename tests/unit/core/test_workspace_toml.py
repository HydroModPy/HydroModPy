"""``workspace.toml`` template generator + Pydantic loader tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.state.paths import WORKSPACE_TOML_FILENAME
from hydromodpy.core.workspace.workspace_toml import (
    DEFAULT_WORKSPACE_TOML_TEMPLATE,
    WorkspaceToml,
    load_workspace_toml,
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


# ---------------------------------------------------------------------------
# Pydantic validation at load
# ---------------------------------------------------------------------------


def _scaffold_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    write_workspace_toml(
        ws,
        project_name="lab",
        creator_name="Alice",
        creator_email="alice@example.com",
        created_at="2026-05-12T00:00:00+00:00",
    )
    return ws


def test_load_workspace_toml_validates_required_fields(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    parsed = load_workspace_toml(ws)
    assert isinstance(parsed, WorkspaceToml)
    assert parsed.workspace.name == "lab"
    assert parsed.workspace.contact == "alice@example.com"
    assert parsed.workspace.created_at == "2026-05-12T00:00:00+00:00"
    assert parsed.conventions.cf == "CF-1.11"
    assert parsed.conventions.acdd == "ACDD-1.3"


def test_load_workspace_toml_rejects_unknown_field(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    toml_path = ws / WORKSPACE_TOML_FILENAME
    content = toml_path.read_text(encoding="utf-8")
    # Inject a sibling unknown key inside the [workspace] table.
    injected = content.replace(
        'hydromodpy_version_min = "2.0.0"',
        'hydromodpy_version_min = "2.0.0"\nrogue_field = "bad"',
    )
    toml_path.write_text(injected, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_workspace_toml_rejects_unknown_top_level_block(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    toml_path = ws / WORKSPACE_TOML_FILENAME
    toml_path.write_text(
        toml_path.read_text(encoding="utf-8") + '\n[unexpected]\nfoo = "bar"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_workspace_toml_rejects_missing_workspace_name(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    toml_path = ws / WORKSPACE_TOML_FILENAME
    toml_path.write_text(
        """\
[workspace]
description = ""
contact = "alice@example.com"
created_at = "2026-05-12T00:00:00+00:00"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_workspace_toml_rejects_empty_workspace_name(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / WORKSPACE_TOML_FILENAME).write_text(
        """\
[workspace]
name = ""
contact = "alice@example.com"
created_at = "2026-05-12T00:00:00+00:00"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_workspace_toml_rejects_missing_contact(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / WORKSPACE_TOML_FILENAME).write_text(
        """\
[workspace]
name = "lab"
created_at = "2026-05-12T00:00:00+00:00"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_roundtrip_preserves_content(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    first = load_workspace_toml(ws)
    # Re-write the same file (no force, idempotent) then reload.
    write_workspace_toml(
        ws,
        project_name="lab",
        creator_name="Alice",
        creator_email="alice@example.com",
    )
    second = load_workspace_toml(ws)
    assert first.workspace.name == second.workspace.name
    assert first.workspace.contact == second.workspace.contact
    assert first.workspace.created_at == second.workspace.created_at
    assert first.workspace.team.members == second.workspace.team.members


def test_load_workspace_toml_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_workspace_toml(tmp_path / "absent")


def test_load_workspace_toml_invalid_bbox(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / WORKSPACE_TOML_FILENAME).write_text(
        """\
[workspace]
name = "lab"
contact = "alice@example.com"
created_at = "2026-05-12T00:00:00+00:00"

[workspace.geographic_scope]
bbox_wgs84 = [1.0, 2.0]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_workspace_toml_model_frozen():
    """The validated model is immutable (frozen=True)."""
    parsed = WorkspaceToml.model_validate(
        {
            "workspace": {
                "name": "lab",
                "contact": "x@y.z",
                "created_at": "2026-05-12T00:00:00+00:00",
            }
        }
    )
    with pytest.raises(ValidationError):
        parsed.workspace.name = "other"  # type: ignore[misc]
