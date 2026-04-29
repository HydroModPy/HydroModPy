"""Step 0 - config validation.

Loads the TOML config (if a path is present in ``state.data["config_path"]``)
and instantiates the Pydantic ``HydroModPyConfig``. If ``state.data["cfg"]``
is already a Pydantic config, it is re-validated to ensure immutability.

Inputs
------
``config_path`` : str or Path (optional if ``cfg`` already present)

Outputs
-------
``cfg`` : HydroModPyConfig
``config_path`` : Path
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import PipelineState, ValidatedState


class ValidateStep:
    """Validate the config via Pydantic."""

    name = "validate"
    tin: ClassVar[type | None] = None
    tout: ClassVar[type] = ValidatedState
    config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.core.config import HydroModPyConfig

        cfg = state.get("cfg")
        config_path = state.get("config_path")

        if cfg is None:
            if config_path is None:
                raise ConfigError("ValidateStep requires 'cfg' or 'config_path' in state.data")
            path = Path(config_path).expanduser().resolve()
            with open(path, "rb") as fh:
                raw = tomllib.load(fh)
            cfg = HydroModPyConfig.model_validate(raw)
            config_path = path
        elif not isinstance(cfg, HydroModPyConfig):
            cfg = HydroModPyConfig.model_validate(cfg)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            cfg=cfg,
            config_path=Path(config_path) if config_path is not None else None,
        )
