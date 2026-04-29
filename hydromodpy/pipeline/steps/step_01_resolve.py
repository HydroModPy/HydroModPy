"""Step 1 - resolve workspace paths, create the workflow context.

Takes a validated config (from :class:`ValidateStep`) and builds a
:class:`WorkflowContext` bound to the config and its source TOML. The
data-load plan is also resolved here so the next step
(:class:`LoadDataStep`) can call the runtime loader without re-running
the planner.

Inputs
------
``cfg`` : HydroModPyConfig
``config_path`` : Path (optional, defaults to ``cfg.workspace`` context)
``raw_toml`` : dict (optional)

Outputs
-------
``ctx`` : WorkflowContext (with ``data_plan`` attached)
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import ClassVar

from hydromodpy.workflow.internals.state import PipelineState, ResolvedState, ValidatedState


class ResolveStep:
    """Resolve workspace + create a ``WorkflowContext`` bound to the config."""

    name = "resolve"
    tin: ClassVar[type] = ValidatedState
    tout: ClassVar[type] = ResolvedState
    config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.core.state.run_state import WorkflowContext
        from hydromodpy.data import DataPlanner
        from hydromodpy.workflow.steps.data_loading import log_data_plan
        from hydromodpy.workflow.steps.setup import support_provider_names

        ctx = state.get("ctx")
        if ctx is None:
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
        else:
            cfg = ctx.cfg
            raw_toml = state.get("raw_toml") or ctx.raw_toml

        if ctx.data_plan is None:
            requested_support_ids = state.get("requested_spatial_support_ids", ()) or ()
            requested_domain_supports = state.get("requested_domain_supports") or {}
            data_plan = DataPlanner().build(
                cfg.data,
                domain_zone_ids=cfg.domain.zone_ids,
                domain_support_provider_names=support_provider_names(requested_domain_supports),
                requested_spatial_support_ids=requested_support_ids,
                raw_toml=raw_toml,
                flow_active_bc=cfg.flow.active_bc,
            )
            log_data_plan(data_plan)
            cfg.data = cfg.data.with_resolved_types(data_plan.types)
            ctx.data_plan = data_plan

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            raw_toml=raw_toml,
        )
