"""Step 9 - derived fields via the :mod:`~hydromodpy.workflow.internals.derived` registry.

Runs the registered :class:`DerivedComputation` objects over the
simulation Zarr store. Each computation is responsible for its own
input check; the step itself is a thin driver that resolves
``ctx.store`` / ``ctx.sim_id``, opens the Zarr, and delegates to
``registry.apply``. Skipped derivations are logged but do not raise.

Inputs
------
``ctx`` : WorkflowContext with ``store`` and ``sim_id`` populated.

Outputs
-------
``ctx`` : unchanged; the Zarr ``/derived`` group gains any computed
fields as a side effect.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.derived import registry as _default_registry
from hydromodpy.workflow.internals.state import DerivedState, ExtractedState, PipelineState

logger = logging.getLogger(__name__)


class DeriveStep:
    """Compute derived fields registered on the :class:`DerivedRegistry`."""

    name = "derive"
    tin: ClassVar[type] = ExtractedState
    tout: ClassVar[type] = DerivedState
    config_sections: ClassVar[tuple[str, ...]] = ("postprocess",)

    def __init__(self, registry=None) -> None:
        self._registry = registry if registry is not None else _default_registry

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DeriveStep requires 'ctx' in state.data")

        store = getattr(ctx, "store", None)
        sim_id = getattr(ctx, "sim_id", None)
        if store is None or sim_id is None:
            logger.debug("DeriveStep: no store/sim_id on ctx, skipping registry application")
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        try:
            sim_zarr = store.open_zarr(sim_id)
        except Exception as exc:
            logger.debug("DeriveStep: cannot open Zarr for sim %s: %s", sim_id, exc)
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        if "head" not in sim_zarr.root:
            logger.debug(
                "DeriveStep: no 'head' field in Zarr for sim %s, nothing to derive",
                sim_id,
            )
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        results = self._registry.apply(sim_zarr)
        for result in results:
            if result.status == "computed":
                logger.debug("DeriveStep: computed '%s'", result.name)
            else:
                logger.debug("DeriveStep: skipped '%s' (%s)", result.name, result.reason)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
