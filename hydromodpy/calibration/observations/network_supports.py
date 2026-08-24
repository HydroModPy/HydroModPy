"""The partition of the mesh the criterion balances, derived in one place.

Three per-cell classes carry the whole reading of a trial: the cells where the
model and the map agree, those the model invents, and those it misses. The cost
counts them, a confusion map draws them and a reference overlay outlines them,
so deriving them twice is how a figure comes to disagree with the number it is
supposed to illustrate.

Nothing here recomputes a distance or a network. It intersects masks the caller
already holds, which is why it is cheap enough to call at every trial.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.calibration.observations.simulated_network import SimulatedNetwork


@dataclass(frozen=True, slots=True)
class CriterionSupports:
    """The masks the two distances are averaged over, and their three classes."""

    keep: np.ndarray
    """(n_cells,) bool: the catchment, active, minus the water bodies."""

    support_so: np.ndarray
    """(n_cells,) bool: the simulated network inside ``keep``, support of ``D_so``."""

    support_os: np.ndarray
    """(n_cells,) bool: the mapped network inside ``keep``, support of ``D_os``."""

    valid: np.ndarray
    """(n_cells,) bool: simulated where the map has a stream."""

    excess: np.ndarray
    """(n_cells,) bool: simulated where the map has none."""

    missing: np.ndarray
    """(n_cells,) bool: mapped where the model produces none."""

    seepage: np.ndarray
    """(n_cells,) bool: the sources inside ``keep``, before the downslope closure."""

    @property
    def counts(self) -> dict[str, float]:
        """The three class sizes, named as a trial publishes them."""
        return {
            "n_valid": float(int(self.valid.sum())),
            "n_excess": float(int(self.excess.sum())),
            "n_missing": float(int(self.missing.sum())),
        }


def criterion_supports(
    *,
    simulated: SimulatedNetwork,
    observed: np.ndarray,
    catchment: np.ndarray,
    active: np.ndarray,
    excluded: np.ndarray | None = None,
) -> CriterionSupports:
    """Intersect the criterion's masks into the partition it scores.

    ``excluded`` holds the cells whose surface-water extent is an input rather
    than an output. They leave both supports here and stay in the graph and in
    the target, which the geometry does on its own side: keeping them in the
    support of ``D_so`` would inject one zero per lake cell and move the root
    with the size of the reservoir rather than with the hydrogeology.
    """
    observed_mask = np.asarray(observed, dtype=bool).reshape(-1)
    keep = np.asarray(catchment, dtype=bool).reshape(-1) & np.asarray(active, dtype=bool).reshape(
        -1
    )
    if excluded is not None:
        keep = keep & ~np.asarray(excluded, dtype=bool).reshape(-1)

    support_so = simulated.network & keep
    support_os = observed_mask & keep
    return CriterionSupports(
        keep=keep,
        support_so=support_so,
        support_os=support_os,
        valid=support_so & observed_mask,
        excess=support_so & ~observed_mask,
        missing=support_os & ~simulated.network,
        seepage=simulated.seepage & keep,
    )


__all__ = ("CriterionSupports", "criterion_supports")
