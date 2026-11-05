"""Step 0 - config validation.

Loads the TOML config (if a path is present in ``state.data["config_path"]``)
and instantiates the Pydantic ``HydroModPyConfig``. If ``state.data["cfg"]``
is already a Pydantic config, it is re-validated to ensure immutability.

The resolved configuration is then written beside the run's resume checkpoint,
under the run directory the pipeline says it owns. It is the step's product:
the user TOML says a fraction of it, and everything downstream reads the
resolved form. The only frozen copy used to be written into the run directory
by ``prepare_solver``, step six, so a run that died while building its model
left none - and the digest the resume checkpoint carries pointed at a document
nobody held.

Inputs
------
``config_path`` : str or Path (optional if ``cfg`` already present)

Outputs
-------
``cfg`` : HydroModPyConfig
``config_path`` : Path
``<run>/.hmp/checkpoints/resolved_config.json``
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from hydromodpy.config.export_checks import check_export_variables, check_time_selectors
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.record.manifest import (
    resolved_config_path,
    state_config_payload,
    write_resolved_config,
)
from hydromodpy.workflow.record.run_store import run_dir_of_state
from hydromodpy.workflow.state import PipelineState


class ValidateStep:
    """Validate the config via Pydantic."""

    name = "validate"
    reads: ClassVar[tuple[str, ...]] = (
        "cfg",
        "config_path",
        "raw_toml",
        "run_dir",
    )
    writes: ClassVar[tuple[str, ...]] = (
        "cfg",
        "config_path",
    )
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
        run_dir = run_dir_of_state(state_out)
        if run_dir is None:
            return ()
        path = resolved_config_path(run_dir)
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

        check_export_variables(cfg)
        check_time_selectors(cfg)

        out = state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            cfg=cfg,
            config_path=Path(config_path) if config_path is not None else None,
        )
        run_dir = run_dir_of_state(out)
        if run_dir is not None:
            write_resolved_config(run_dir, out.run_id, state_config_payload(out))
        return out
