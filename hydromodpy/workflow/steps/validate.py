"""Step 0 - config validation.

Loads the TOML config (if a path is present in ``state.data["config_path"]``)
and instantiates the Pydantic ``HydroModPyConfig``. If ``state.data["cfg"]``
is already a Pydantic config, it is re-validated to ensure immutability.

The resolved configuration is then written beside the run's resume checkpoint,
in the workspace the pipeline says it owns a record in. It is the step's
product: the user TOML says a fraction of it, and everything downstream reads
the resolved form. The only frozen copy used to be written into the run
directory by ``prepare_solver``, step six, so a run that died while building
its model left none - and the digest the resume checkpoint carries pointed at
a document nobody held.

Inputs
------
``config_path`` : str or Path (optional if ``cfg`` already present)

Outputs
-------
``cfg`` : HydroModPyConfig
``config_path`` : Path
``<project_root>/.hmp/checkpoints/<run_id>/resolved_config.json``
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.manifest import (
    resolved_config_path,
    state_config_payload,
    write_resolved_config,
)
from hydromodpy.workflow.internals.state import PipelineState, ValidatedState


def _run_workspace_for(state: PipelineState) -> Path | None:
    """Return the workspace this run owns a record in, or None.

    The pipeline decides, never the config: a window that stops before
    ``setup_process`` registers no simulation and is handed no workspace, and a
    calibration prefix runs with none at all. Either of them writing where the
    config points would overwrite the documents of the run that carries the
    same name.
    """
    workspace = state.get("run_workspace")
    if workspace is None:
        return None
    path = Path(str(workspace))
    return path if path.is_dir() else None


class ValidateStep:
    """Validate the config via Pydantic."""

    name = "validate"
    tin: ClassVar[type | None] = None
    tout: ClassVar[type] = ValidatedState
    config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

    def depends_on(self) -> tuple[str, ...]:
        return ()

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Re-run validation: idempotent, and it rewrites what it resolved."""
        return self.run(prior_state)

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return the resolved configuration this step wrote, when it wrote one."""
        workspace = _run_workspace_for(state_out)
        if workspace is None:
            return ()
        path = resolved_config_path(workspace, state_out.run_id)
        return (str(path),) if path.is_file() else ()

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.config import HydroModPyConfig

        cfg = state.get("cfg")
        config_path = state.get("config_path")

        if cfg is None:
            if config_path is None:
                raise ConfigError("ValidateStep requires 'cfg' or 'config_path' in state.data")
            path = Path(config_path).expanduser().resolve()
            cfg = HydroModPyConfig.from_toml(path)
            config_path = path
        elif not isinstance(cfg, HydroModPyConfig):
            cfg = HydroModPyConfig.model_validate(cfg)

        out = state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            cfg=cfg,
            config_path=Path(config_path) if config_path is not None else None,
        )
        workspace = _run_workspace_for(out)
        if workspace is not None:
            write_resolved_config(workspace, out.run_id, state_config_payload(out))
        return out
