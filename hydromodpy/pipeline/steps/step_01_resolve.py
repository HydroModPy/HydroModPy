"""Step 1 - resolve workspace paths, create the workflow context.

Takes a validated config (from :class:`ValidateStep`) and builds a
:class:`WorkflowContext` bound to the config and its source TOML. This
is the point where the in-memory config becomes associated with
filesystem locations.

Inputs
------
``cfg`` : HydroModPyConfig
``config_path`` : Path (optional, defaults to ``cfg.workspace`` context)
``raw_toml`` : dict (optional)

Outputs
-------
``ctx`` : WorkflowContext
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import ClassVar

from hydromodpy.pipeline.state import PipelineState, ResolvedState, ValidatedState


class ResolveStep:
    """Resolve workspace + create a ``WorkflowContext`` bound to the config."""

    name = "resolve"
    tin: ClassVar[type] = ValidatedState
    tout: ClassVar[type] = ResolvedState
    config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.core.state.run_state import WorkflowContext

        ctx = state.get("ctx")
        if ctx is not None:
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        cfg = state.get("cfg")
        if cfg is None:
            raise ValueError("ResolveStep requires 'cfg' in state.data")

        config_path = state.get("config_path")
        if config_path is None:
            raise ValueError("ResolveStep requires 'config_path' (or a pre-built 'ctx')")
        config_path = Path(config_path).expanduser().resolve()

        raw_toml = state.get("raw_toml")
        if raw_toml is None:
            with open(config_path, "rb") as fh:
                raw_toml = tomllib.load(fh)

        ctx = WorkflowContext(cfg=cfg, config_path=config_path, raw_toml=raw_toml)
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            raw_toml=raw_toml,
        )
