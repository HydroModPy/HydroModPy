"""Run a HydroModPy ``Pipeline`` behind an external validity frame.

Run after installing both packages locally (editable)::

    pip install -e . -e validity_frame
    python validity_frame/examples/hydromodpy_pipeline.py

The helper below is the whole integration point: verify first, then delegate to
``Pipeline.run``. Nothing in ``hydromodpy`` needs to know this package exists.
"""

from __future__ import annotations

from typing import Any, Protocol

from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline
from validity_frame import ValidityFrame

logger = get_logger(__name__)


class ValidityFrameProtocol(Protocol):
    """Minimal contract an external validity frame must honour.

    ``verify`` raises when the state is invalid.
    """

    def verify(
        self, state: PipelineState, steps: tuple
    ) -> None:  # pragma: no cover - simple protocol
        ...


def run_pipeline_with_validity(
    pipeline: Pipeline,
    state: PipelineState,
    *,
    validity_frame: ValidityFrameProtocol | None = None,
    raise_on_failure: bool = True,
    **run_kwargs: Any,
) -> PipelineState:
    """Verify ``validity_frame`` when given, then call ``Pipeline.run``.

    ``raise_on_failure=False`` logs the verification error and runs anyway.
    ``run_kwargs`` is forwarded to ``Pipeline.run`` (``parallel``,
    ``resume_from``, ...).
    """
    if validity_frame is not None:
        try:
            validity_frame.verify(state, pipeline.steps)
        except Exception:  # pragma: no cover - branch for user policy
            logger.exception("validity_frame verification failed")
            if raise_on_failure:
                raise
    return pipeline.run(state, **run_kwargs)


if __name__ == "__main__":
    pipeline = Pipeline(steps=(), workspace=None)
    state = PipelineState(run_id="validity-frame-demo", data={"seeded": True})
    run_pipeline_with_validity(
        pipeline,
        state,
        validity_frame=ValidityFrame(tolerant=True),
        parallel=False,
    )
    print("pipeline ran behind ValidityFrame")
