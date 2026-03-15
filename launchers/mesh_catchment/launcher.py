"""Dedicated launcher for catchment meshing workflows.

This launcher intentionally does one thing: generate a 2D conformal mesh from
one catchment setup, enforcing conformity to the river network trace while
ignoring geology interfaces for meshing.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from typing import Any

# When this file is executed directly by path, Python adds the script folder to
# ``sys.path`` but not necessarily the repository root. Insert the repo root
# explicitly so local imports always resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import _load_standard_section
from hydromodpy.config.toml_loader import load_toml_with_base_config
from hydromodpy.geographic.core.domain_geographic_pipeline import (
    build_domain_geographic_context,
)
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal import (
    run_reference_2d_geology_conformal_case_from_toml,
)
from launchers.output_paths import (
    build_repo_output_redirect_notice,
    resolve_launcher_output_root,
)


DEFAULT_CONFIG_NAME = "config_mesh_catchment_example.toml"


class MeshCatchmentLauncher:
    """Run one mesh-only workflow from the ``[mesh_catchment]`` TOML section."""

    SECTION_NAME = "mesh_catchment"
    _RIVER_TRACE_MESH_MODES = {"rivers", "both"}

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = self._require_mesh_section(self.raw_toml)
        self.workspace_cfg, self.geographic_cfg = self._load_runtime_configs(
            self.raw_toml
        )
        self.mesh_mode = self._resolve_mesh_mode(
            self.mesh_section_data.get("mesh_mode", "rivers")
        )
        self.geographic_cfg = self._prepare_geographic_config_for_meshing(
            self.geographic_cfg,
            mesh_mode=self.mesh_mode,
        )

        resolved_out_dir, resolution = resolve_launcher_output_root(
            self.workspace_cfg.out_dir_path,
        )
        self.workspace_cfg.out_dir_path = resolved_out_dir
        if resolution == "repo_redirect":
            print(
                build_repo_output_redirect_notice(
                    entrypoint_name="MeshCatchmentLauncher",
                    resolved_out_dir=resolved_out_dir,
                )
            )

    def _load_runtime_configs(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[WorkspaceConfig, GeographicConfig]:
        """Load only workspace/geographic sections needed by this mesh-only launcher."""
        base_dir = self.config_path.parent
        workspace_cfg = _load_standard_section(
            payload.get("workspace", {}),
            WorkspaceConfig,
            base_dir,
        )
        geographic_cfg = _load_standard_section(
            payload.get("geographic", {}),
            GeographicConfig,
            base_dir,
        )
        return workspace_cfg, geographic_cfg

    @classmethod
    def _resolve_mesh_mode(cls, raw_value: Any) -> str:
        token = str(raw_value).strip().lower()
        if token == "":
            token = "rivers"
        aliases = {
            "geology": "geology",
            "zones": "geology",
            "rivers": "rivers",
            "river": "rivers",
            "hydrography": "rivers",
            "hydro": "rivers",
            "both": "both",
            "geology+rivers": "both",
            "geology_and_rivers": "both",
        }
        mode = aliases.get(token)
        if mode is None:
            raise ValueError(
                "mesh_catchment.mesh_mode must be one of: geology, rivers, both "
                "(aliases: zones, river, hydrography, geology+rivers)."
            )
        return mode

    @classmethod
    def _require_mesh_section(cls, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        section = payload.get(cls.SECTION_NAME)
        if not isinstance(section, Mapping):
            raise ValueError(
                "Missing [mesh_catchment] section in launcher TOML. "
                "Expected one mapping compatible with the conformal meshing case schema."
            )
        return section

    @classmethod
    def _mesh_mode_requires_river_trace(cls, mesh_mode: str) -> bool:
        return str(mesh_mode).strip().lower() in cls._RIVER_TRACE_MESH_MODES

    @classmethod
    def _prepare_geographic_config_for_meshing(
        cls,
        geographic_cfg: GeographicConfig,
        *,
        mesh_mode: str,
    ) -> GeographicConfig:
        if not cls._mesh_mode_requires_river_trace(mesh_mode):
            return geographic_cfg
        if geographic_cfg.uses_synthetic_geographic():
            return geographic_cfg
        if bool(getattr(geographic_cfg.river_network, "enabled", False)):
            return geographic_cfg

        # Rivers-based meshing requires in-memory river_trace generation from
        # geographic preprocessing. Turn it on explicitly when needed.
        updated = geographic_cfg.model_copy(
            update={
                "river_network": geographic_cfg.river_network.model_copy(
                    update={"enabled": True}
                )
            }
        )
        # Re-validate to fail fast when threshold parameters are incomplete.
        return GeographicConfig.model_validate(updated.model_dump())

    def _build_domain_geographic_context(self, workspace):
        """Build domain-level geographic context with optional in-memory river trace."""
        return build_domain_geographic_context(
            config=self.geographic_cfg,
            workspace=workspace,
        )

    def _resolve_river_trace_for_launcher(self, domain_geographic: object | None) -> object | None:
        if domain_geographic is None:
            return None
        return getattr(domain_geographic, "river_mesh_trace", None)

    def _validate_river_trace_requirement(self, *, river_trace: object | None) -> None:
        if not self._mesh_mode_requires_river_trace(self.mesh_mode):
            return
        if river_trace is not None:
            return
        if self.geographic_cfg.uses_synthetic_geographic():
            raise ValueError(
                "mesh_catchment.mesh_mode requires river_trace, but synthetic geographic "
                "mode does not generate river networks."
            )
        raise ValueError(
            "mesh_catchment.mesh_mode requires river_trace, but no in-memory "
            "river trace was generated. Ensure [geographic.river_network] is enabled "
            "with valid threshold parameters."
        )

    @staticmethod
    def _resolve_optional_path(
        *,
        config_dir: Path,
        raw_value: Any,
    ) -> Path | None:
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        if text == "":
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (config_dir / path).resolve()
        return path

    def _resolve_output_overrides(self, workspace) -> tuple[Path, Path, Path | None, bool]:
        section = self.mesh_section_data
        config_dir = self.config_path.parent

        output_mesh = self._resolve_optional_path(
            config_dir=config_dir,
            raw_value=section.get("output_mesh"),
        )
        if output_mesh is None:
            output_mesh = Path(workspace.stable_folder) / "mesh" / "gmsh" / "mesh_catchment.msh"

        output_summary_json = self._resolve_optional_path(
            config_dir=config_dir,
            raw_value=section.get("output_summary_json"),
        )
        if output_summary_json is None:
            output_summary_json = (
                Path(workspace.stable_folder)
                / "mesh"
                / "gmsh"
                / "mesh_catchment_summary.json"
            )

        output_figure = self._resolve_optional_path(
            config_dir=config_dir,
            raw_value=section.get("output_figure"),
        )

        raw_show_plot = section.get("show_plot", False)
        show_plot = bool(raw_show_plot) if isinstance(raw_show_plot, bool) else False
        return output_mesh, output_summary_json, output_figure, show_plot

    def run(self) -> dict[str, Any]:
        """Execute the mesh-only launcher and return the generated summary."""
        workspace = hmp.Workspace(config=self.workspace_cfg)
        domain_geographic = self._build_domain_geographic_context(workspace)
        river_trace = self._resolve_river_trace_for_launcher(domain_geographic)
        self._validate_river_trace_requirement(river_trace=river_trace)

        output_mesh, output_summary_json, output_figure, show_plot = (
            self._resolve_output_overrides(workspace)
        )

        summary = run_reference_2d_geology_conformal_case_from_toml(
            self.config_path,
            section=self.SECTION_NAME,
            output_mesh=output_mesh,
            output_summary_json=output_summary_json,
            output_figure=output_figure,
            river_trace=river_trace,
            domain_geographic=domain_geographic,
            mesh_mode_override=self.mesh_mode,
            show_plot=show_plot,
        )
        return dict(summary)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the mesh-catchment launcher with a TOML config.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / DEFAULT_CONFIG_NAME,
        help=f"Path to launcher TOML file (default: {DEFAULT_CONFIG_NAME}).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run mesh-catchment launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    summary = MeshCatchmentLauncher(args.config.expanduser().resolve()).run()
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
