"""Helpers to render canonical TOML templates for mesh-catchment launchers."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.config.generate_toml import generate_toml


def render_mesh_catchment_template(
    *,
    batch: bool = False,
    profile: str = "user",
    include_base_config: bool = True,
) -> str:
    """Render one commented TOML template derived from Pydantic schemas."""
    modules = ["mesh_catchment_batch", "mesh_catchment"] if batch else ["mesh_catchment"]
    command = "python -m launchers mesh-catchment template --batch"
    if not batch:
        command = "python -m launchers mesh-catchment template"

    lines = [
        "# Auto-generated mesh-catchment launcher template.",
        "# Regenerate with:",
        f"#   {command} --profile {profile}",
        "",
    ]
    if include_base_config:
        lines.extend(
            [
                '# Shared launcher bootstrap. Override this if your project uses another common base.',
                'base_config = "config_mesh_catchment_common.toml"',
                "",
            ]
        )

    body = generate_toml(modules=modules, profile=profile)
    return "\n".join(lines) + body


def write_mesh_catchment_template(
    *,
    output_path: str | Path,
    batch: bool = False,
    profile: str = "user",
    include_base_config: bool = True,
) -> str:
    """Render and write one canonical mesh-catchment TOML template."""
    content = render_mesh_catchment_template(
        batch=batch,
        profile=profile,
        include_base_config=include_base_config,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return content


__all__ = [
    "render_mesh_catchment_template",
    "write_mesh_catchment_template",
]
