"""Observations step - ingest piezometry and hydrometry observations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_ingest_observations(ctx: WorkflowContext, sim_id: str) -> None:
    """Ingest observation timeseries associated with this simulation.

    Failures are swallowed and logged. Observations are an enrichment of the
    run record, not a requirement, so they never block finalize.
    """
    from hydromodpy.simulation.extraction.extractors.observation_ingest import (
        ingest_observations,
    )

    try:
        ingest_observations(sim_id, ctx.store, ctx.loaded_data)
    except Exception:
        logger.exception("Failed to ingest observations for sim %s", sim_id)
