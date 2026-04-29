"""Dedicated launcher for catchment meshing workflows.

This module is the user-facing entry point of the mesh-only workflow. It does
not generate meshes by itself; instead it performs the small amount of
orchestration work that turns one launcher TOML into the concrete runtime
objects consumed by geographic preprocessing and by the 2D conformal meshing
case.

The key design choice is that batch orchestration now lives in
``launchers.mesh_catchment.batch``. This launcher therefore stays focused on:

- loading and validating the launcher-specific section;
- loading the shared runtime sections (`workspace`, `geographic`, optional
  `domain`);
- preparing the geographic config for the chosen constraints mode;
- delegating either to one mono-catchment run or to the batch runner.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.master_config.hydromodpy_config import _load_standard_section
from hydromodpy.master_config.toml_loader import load_toml_with_base_config
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh import runtime as mesh_runtime
from hydromodpy.spatial.mesh.batch import (
    MeshCatchmentBatchConfig,
    MeshCatchmentBatchRunner,
)

DEFAULT_CONFIG_NAME = "scenarios/config_example.toml"


class MeshCatchmentLauncher:
    """Run one mesh-only workflow from the ``[mesh_catchment]`` TOML section."""

    SECTION_NAME = "mesh_catchment"

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = mesh_runtime.require_mesh_section(self.raw_toml)
        self.workspace_cfg, self.geographic_cfg, self.domain_cfg = self._load_runtime_configs(
            self.raw_toml
        )
        self.constraints_mode = self.mesh_section_data.constraints_mode
        self.geographic_cfg = mesh_runtime.prepare_geographic_config_for_meshing(
            self.geographic_cfg,
            constraints_mode=self.constraints_mode,
            section_name=self.SECTION_NAME,
        )
        self.batch_cfg = MeshCatchmentBatchConfig.from_mapping(
            self.raw_toml.get("mesh_catchment_batch"),
            base_dir=self.config_path.parent,
        )
        self.batch_runner: MeshCatchmentBatchRunner | None = None
        if self.batch_cfg is not None:
            self.batch_runner = MeshCatchmentBatchRunner(
                config_path=self.config_path,
                mesh_section_data=self.mesh_section_data,
                workspace_cfg=self.workspace_cfg,
                geographic_cfg=self.geographic_cfg,
                domain_cfg=self.domain_cfg,
                run_single_workflow=self._run_single_workflow,
            )
            self.batch_runner.run_preflight(self.batch_cfg)

    def _normalize_workspace_section(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return one workspace payload with launcher-friendly defaults applied."""
        base_dir = self.config_path.parent
        workspace_data = dict(payload.get("workspace", {}))
        if not workspace_data.get("project_root"):
            workspace_data["project_root"] = str(base_dir)
        return workspace_data

    def _load_runtime_configs(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[WorkspaceConfig, GeographicConfig, DomainConfig]:
        """Load the shared runtime sections consumed by the launcher."""
        base_dir = self.config_path.parent
        workspace_cfg = _load_standard_section(
            self._normalize_workspace_section(payload),
            WorkspaceConfig,
            base_dir,
        )
        geographic_cfg = _load_standard_section(
            payload.get("geographic", {}),
            GeographicConfig,
            base_dir,
        )
        if "domain" in payload:
            domain_cfg = _load_standard_section(
                payload.get("domain", {}),
                DomainConfig,
                base_dir,
            )
        else:
            domain_cfg = DomainConfig()
        return workspace_cfg, geographic_cfg, domain_cfg

    def _run_single_workflow(
        self,
        *,
        workspace_cfg: object,
        geographic_cfg: GeographicConfig,
        domain_cfg: object,
        output_overrides: Mapping[str, Path | None] | None = None,
    ) -> dict[str, Any]:
        """Delegate one fully prepared mono-catchment run to the shared runtime layer."""
        return mesh_runtime.run_single_mesh_catchment_workflow(
            config_path=self.config_path,
            section_data=self.mesh_section_data,
            workspace_cfg=workspace_cfg,
            geographic_cfg=geographic_cfg,
            domain_cfg=domain_cfg,
            constraints_mode=self.constraints_mode,
            output_overrides=output_overrides,
            section_name=self.SECTION_NAME,
        )

    def run(self) -> dict[str, Any]:
        """Execute the launcher and return the final summary payload."""
        if self.batch_cfg is not None:
            if self.batch_runner is None:  # pragma: no cover - defensive only
                raise PipelineError("Batch runner was not initialized.")
            return self.batch_runner.run(self.batch_cfg)
        return self._run_single_workflow(
            workspace_cfg=self.workspace_cfg,
            geographic_cfg=self.geographic_cfg,
            domain_cfg=self.domain_cfg,
        )


def _build_parser() -> argparse.ArgumentParser:
    """Build the small CLI parser used when launching this module directly."""
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
    """Run the mesh-catchment launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    summary = MeshCatchmentLauncher(args.config.expanduser().resolve()).run()
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
