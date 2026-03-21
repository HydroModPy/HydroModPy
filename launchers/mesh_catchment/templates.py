"""Template helpers for the mesh-catchment launcher family.

This module does not own the launcher schema; the Pydantic models remain the
authoritative source of truth. Its job is narrower and more editorial:
generate starter TOMLs that are pleasant to read and that expose the launcher
conventions users need first.

In other words:

- schema models decide which keys exist and how they are validated;
- `generate_toml()` renders the bulk of the commented template from those
  models;
- this module injects the mesh-catchment-specific framing that would otherwise
  be missing from a generic auto-generated template.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from hydromodpy.config.generate_toml import generate_toml


_OUTPUT_LAYOUT_BLOCK = dedent(
    """
    # Dedicated-launcher output layout.
    # Use 'standard' to keep final mesh artifacts under `results_stable/mesh/`, or 'flat' to write final mesh artifacts directly under `workspace.project_root` while keeping intermediate runtime folders out of that final directory.
    # Type: string | Default: "standard"
    output_layout = "standard"
    """
).strip()


def _inject_output_layout_block(body: str) -> str:
    """Insert the launcher-specific output-layout block in generated TOML text.

    ``output_layout`` is a dedicated-launcher concern, not a generic
    HydroModPy config concept. We therefore inject it after the generic TOML
    generation step so the template stays schema-driven while still documenting
    one of the most important practical choices of the mesh launcher.
    """
    if "output_layout = " in body:
        return body
    # We inject the block right before the existing "show_plot" comment because
    # that keeps all output-related controls grouped together in the final
    # template: mesh paths, figures, layout, then interactive display.
    marker = (
        "# If true, open the generated overview figure interactively at the end of the run.\n"
    )
    replacement = f"{_OUTPUT_LAYOUT_BLOCK}\n\n{marker}"
    if marker not in body:
        raise ValueError("Could not inject output_layout block into mesh-catchment template.")
    return body.replace(marker, replacement, 1)


def render_mesh_catchment_template(
    *,
    batch: bool = False,
    profile: str = "user",
    include_base_config: bool = True,
) -> str:
    """Render one commented TOML template derived from the launcher schemas.

    The template intentionally starts with a short hand-written header before
    the auto-generated schema body. That header answers the two questions users
    most often have when they first open the file:

    - how do I regenerate this template later?
    - which shared base config is assumed by default?
    """
    modules = ["mesh_catchment_batch", "mesh_catchment"] if batch else ["mesh_catchment"]
    command = "python -m launchers mesh-catchment template --batch"
    if not batch:
        command = "python -m launchers mesh-catchment template"

    # Keep the generated header short and actionable so users can regenerate
    # the file instead of editing stale copies by hand, while still making the
    # default inheritance chain explicit.
    lines = [
        "# Auto-generated mesh-catchment launcher template.",
        "# Regenerate with:",
        f"#   {command} --profile {profile}",
        "",
    ]
    if include_base_config:
        base_config_name = "config_batch_common.toml" if batch else "config_common.toml"
        lines.extend(
            [
                '# Shared launcher bootstrap. Override this if your project uses another common base.',
                f'base_config = "{base_config_name}"',
                "",
            ]
        )

    body = generate_toml(modules=modules, profile=profile)
    # `generate_toml()` knows about the schema comments. This helper adds the
    # dedicated-launcher conventions that are not naturally expressed by the
    # generic schema renderer, such as the output-layout explanation above.
    body = _inject_output_layout_block(body)
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
