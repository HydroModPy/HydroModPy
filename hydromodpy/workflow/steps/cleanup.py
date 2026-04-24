"""Cleanup step - remove solver scratch directory when not retained."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)


def step_cleanup_scratch(
    ctx: WorkflowContext,
    *,
    keep_solver_files: bool = False,
) -> None:
    """Remove .solver_scratch/ unless keep_solver_files is True."""
    if keep_solver_files:
        return
    workspace = ctx.setup.workspace
    if workspace is None:
        return
    scratch = workspace.solver_scratch_folder
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
