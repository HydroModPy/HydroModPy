"""Protocol contracts that the calibration trial primitives consume.

The calibration package must not import the workflow package (layer-matrix
rule). The trial primitive nevertheless needs a Pipeline driver, the
ordered list of standard steps, the dependency-cut helper, the structural
data binder, and the spatial-support resolvers. All of those live in the
workflow layer.

This module defines:

- a :class:`TrialPipelineProvider` Protocol that bundles every callable the
  trial primitive needs from the workflow layer,
- a registration pair (:func:`register_trial_pipeline_provider` /
  :func:`get_trial_pipeline_provider`) the bootstrap wires up at import time.

The concrete provider is instantiated by ``hydromodpy.workflow.steps.calibration``
and registered from ``hydromodpy._bootstrap``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TrialStep(Protocol):
    """Minimal pipeline step contract used by the trial primitive."""

    name: str

    def run(self, state_in: Any) -> Any:
        """Execute the step and return the next state."""


@runtime_checkable
class TrialPipelineRunner(Protocol):
    """Minimal pipeline runner contract used by the trial primitive."""

    def run(self, state: Any) -> Any:
        """Execute every step over ``state`` and return the final state."""


@runtime_checkable
class TrialPipelineProvider(Protocol):
    """Bundle of workflow callables consumed by the trial primitive.

    The trial primitive resolves this provider through
    :func:`get_trial_pipeline_provider` rather than importing the workflow
    package directly. The bootstrap registers a concrete implementation
    backed by :class:`hydromodpy.workflow.runner.Pipeline` and friends.
    """

    def standard_steps(self) -> Sequence[TrialStep]:
        """Return the canonical ordered pipeline steps."""

    def earliest_affected_step(
        self,
        override_paths: Iterable[str],
        steps: Sequence[TrialStep],
    ) -> int:
        """Return the lowest step index affected by any override path."""

    def make_pipeline(self, steps: Sequence[TrialStep]) -> TrialPipelineRunner:
        """Build a pipeline runner over the given steps."""

    def make_state(self, run_id: str, data: Mapping[str, Any]) -> Any:
        """Build a fresh pipeline state from ``run_id`` and an initial data mapping."""

    def collect_requested_support_ids(self, flow_cfg: object) -> tuple[str, ...]:
        """Discover spatial supports referenced by heterogeneous flow parameters."""

    def resolve_support_configs(
        self,
        domain_cfg: object,
        requested_support_ids: tuple[str, ...],
    ) -> dict[str, object]:
        """Resolve declared support configs for the requested ids."""

    def build_default_spatial_support_provider_registry(self) -> object:
        """Return the default spatial-support provider registry."""

    def apply_structural_updates_from_data(self, ctx: Any) -> None:
        """Bind freshly loaded data objects to runtime structures on ``ctx``."""


@runtime_checkable
class TrialPromotionProvider(Protocol):
    """Bundle that promotes a calibration candidate to a persisted run."""

    def promote_trial(
        self,
        cfg_path: str | Path,
        values: Mapping[str, float],
        *,
        paths: Mapping[str, str] | None = None,
        name: str | None = None,
        tags: Sequence[str] = (),
        session_id: str | None = None,
    ) -> str:
        """Run a full simulation with calibration values baked in."""


_provider: TrialPipelineProvider | None = None
_promotion_provider: TrialPromotionProvider | None = None


def register_trial_pipeline_provider(provider: TrialPipelineProvider) -> None:
    """Register the workflow-backed provider used by the trial primitive."""
    global _provider
    _provider = provider


def get_trial_pipeline_provider() -> TrialPipelineProvider:
    """Return the registered provider, or raise if none is wired."""
    if _provider is None:
        raise RuntimeError(
            "TrialPipelineProvider is not registered. "
            "Import 'hydromodpy' (or call hydromodpy.bootstrap()) before "
            "using calibration trial primitives."
        )
    return _provider


def register_trial_promotion_provider(provider: TrialPromotionProvider) -> None:
    """Register the provider used by legacy trial promotion helpers."""
    global _promotion_provider
    _promotion_provider = provider


def get_trial_promotion_provider() -> TrialPromotionProvider:
    """Return the registered promotion provider, or raise if none is wired."""
    if _promotion_provider is None:
        raise RuntimeError(
            "TrialPromotionProvider is not registered. "
            "Import 'hydromodpy' (or call hydromodpy.bootstrap()) before "
            "promoting calibration trials."
        )
    return _promotion_provider


__all__ = [
    "TrialPipelineProvider",
    "TrialPipelineRunner",
    "TrialPromotionProvider",
    "TrialStep",
    "get_trial_pipeline_provider",
    "get_trial_promotion_provider",
    "register_trial_pipeline_provider",
    "register_trial_promotion_provider",
]
