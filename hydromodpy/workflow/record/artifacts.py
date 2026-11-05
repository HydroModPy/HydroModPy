"""The artifacts a step names, as workspace-relative URIs for the journal."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.contracts.workflow_step import step_name
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.step import Step

logger = get_logger(__name__)


def collect_artifacts(
    step: Step,
    state_out: PipelineState,
    workspace: Path | None,
) -> tuple[str, ...]:
    """Ask ``step.artifacts(state_out)`` and normalize to workspace-relative POSIX URIs."""
    method = getattr(step, "artifacts", None)
    if method is None:
        return ()
    try:
        raw = method(state_out)
    except Exception as exc:
        logger.debug(
            "step.artifacts_failed name=%s err=%s",
            step_name(step),
            exc,
        )
        return ()
    if not raw:
        return ()
    normalised: list[str] = []
    for item in raw:
        rel = _to_relative_uri(item, workspace)
        if rel is None:
            continue
        normalised.append(rel)
    return tuple(sorted(set(normalised)))


def _to_relative_uri(item: object, workspace: Path | None) -> str | None:
    """Convert a candidate artifact reference to a workspace-relative URI."""
    if item is None:
        return None
    if isinstance(item, Path):
        path = item
    else:
        path = Path(str(item))
    if workspace is not None and path.is_absolute():
        try:
            return path.relative_to(workspace).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()
