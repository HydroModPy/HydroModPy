"""Helpers pour lancer un `Pipeline` en injectant une validity frame externe.

Usage:
    from hydromodpy.workflow.runner import Pipeline
    from hydromodpy.workflow.internals.state import PipelineState
    from scripts.run_helpers import run_pipeline_with_validity, MyValidityFrame

    pipeline = Pipeline(steps, workspace=...)
    state = PipelineState(run_id="my-run", data={})
    validity = MyValidityFrame(tolerant=True)
    run_pipeline_with_validity(pipeline, state, validity_frame=validity, parallel=True)

Ce module ne modifie aucun fichier dans `hydromodpy` et reste découplé.
"""

from __future__ import annotations

from collections.abc import Protocol
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline

logger = get_logger(__name__)


class ValidityFrameProtocol(Protocol):
    """Contrat minimal pour un validity frame externe.

    La méthode `verify` doit lever une exception en cas d'invalidité.
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
    """Vérifie `validity_frame` (si fourni), puis appelle `Pipeline.run`.

    - `validity_frame` : objet conforme à `ValidityFrameProtocol` fourni par
      l'appelant (out-of-tree). Le runner reste découplé de hydromodpy.
    - `raise_on_failure` : si False, on log l'erreur et on continue.
    - `run_kwargs` : transmis à `Pipeline.run` (p.ex. `parallel=True`).
    """
    if validity_frame is not None:
        try:
            validity_frame.verify(state, pipeline.steps)
        except Exception:  # pragma: no cover - branch for user policy
            logger.exception("validity_frame verification failed")
            if raise_on_failure:
                raise
    return pipeline.run(state, **run_kwargs)


class MyValidityFrame:
    """Exemple minimal d'implémentation de validity frame, hors package.

    Remplace cette classe par ton implémentation réelle. Elle ne dépend pas
    de `hydromodpy` et est fournie ici uniquement comme modèle.
    """

    def __init__(self, tolerant: bool = False) -> None:
        self.tolerant = bool(tolerant)

    def verify(self, state: PipelineState, steps: tuple) -> None:
        """Vérifie quelques invariants simples.

        Lève `RuntimeError` si l'état est manifestement invalide (ex: pas de
        `data`), sauf si `tolerant=True`.
        """
        # Exemple simple : s'assurer que `state.data` existe
        if getattr(state, "data", None) in (None, {}, ""):
            msg = "validity_frame: state.data is empty or missing"
            if self.tolerant:
                logger.warning(msg)
                return
            raise RuntimeError(msg)


__all__ = ["ValidityFrameProtocol", "run_pipeline_with_validity", "MyValidityFrame"]
