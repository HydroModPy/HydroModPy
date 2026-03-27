"""Helpers to render canonical TOML templates for the data-overview launcher."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.config.generate_toml import generate_toml


def render_overview_template(
    *,
    profile: str = "user",
) -> str:
    """Render one commented TOML template derived from Pydantic schemas."""
    modules = ["workspace", "geographic", "data", "overview"]

    lines = [
        "# Auto-generated data-overview launcher template.",
        "# Regenerate with:",
        f"#   python -m launchers data-overview template",
        "#",
        "# Usage:",
        "#   hmp overview config_overview.toml",
        "#   python -m launchers data-overview run config_overview.toml",
        "",
    ]

    body = generate_toml(modules=modules, profile=profile)
    return "\n".join(lines) + body


def write_overview_template(output_path: str | Path, *, profile: str = "user") -> None:
    """Render and write one canonical data-overview TOML template."""
    content = render_overview_template(profile=profile)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


__all__ = [
    "render_overview_template",
    "write_overview_template",
]
