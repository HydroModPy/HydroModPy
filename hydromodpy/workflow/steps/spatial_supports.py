"""Spatial-supports step — materialize declared domain spatial supports.

Delegates to ``build_domain_spatial_supports`` which now lives in
``hydromodpy.workflow.steps.setup``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import LauncherRunState


def step_spatial_supports(
    ctx: LauncherRunState,
    *,
    phase: str,
    requested_domain_supports: dict[str, object] | None = None,
    registry: object | None = None,
) -> None:
    """Materialize declared spatial supports for the given build *phase*."""
    if requested_domain_supports is None:
        requested_domain_supports = {}
    if not requested_domain_supports:
        return

    from hydromodpy.workflow.steps.setup import build_domain_spatial_supports

    if registry is None:
        from hydromodpy.spatial.domain.spatial_support import (
            build_default_spatial_support_provider_registry,
        )

        registry = build_default_spatial_support_provider_registry()

    build_domain_spatial_supports(
        cfg=ctx.cfg,
        run_state=ctx,
        requested_domain_supports=requested_domain_supports,
        registry=registry,
        phase=phase,
    )
