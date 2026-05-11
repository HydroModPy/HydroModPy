"""Simulated active-network and release-flux views for :class:`Run`.

Mixin that exposes lazy mask, metric and distance accessors for the
simulated active drainage network and the direct release flux output.
Mixed into :class:`hydromodpy.results.run.Run`.
"""

from __future__ import annotations

import numpy as np


class RunSimulatedMixin:
    """Simulated-output view delegators mixed into :class:`Run`."""

    def simulated_active_network_mask(self, **kwargs) -> np.ndarray:
        """Lazy per-cell active-network mask from accumulation flux."""
        from hydromodpy.results import views

        return views.simulated_active_network_mask(self, **kwargs)

    def simulated_active_network_metrics(self, **kwargs) -> dict[str, float | int | str]:
        """Lazy scalar summary of active drainage occupancy from accumulation flux."""
        from hydromodpy.results import views

        return views.simulated_active_network_metrics(self, **kwargs)

    def simulated_active_network_overlap_metrics(self, **kwargs) -> dict[str, float | int | str]:
        """Lazy cell-overlap metrics against one persisted vector network role."""
        from hydromodpy.results import views

        return views.simulated_active_network_overlap_metrics(self, **kwargs)

    def simulated_active_network_distance_metrics(
        self,
        **kwargs,
    ) -> dict[str, float | int | str | None]:
        """Lazy planar distance metrics against one persisted vector network role."""
        from hydromodpy.results import views

        return views.simulated_active_network_distance_metrics(self, **kwargs)

    def release_flux_network_overlap_metrics(self, **kwargs) -> dict[str, float | int | str]:
        """Lazy cell-overlap metrics for direct release flux against a vector network."""
        from hydromodpy.results import views

        return views.release_flux_network_overlap_metrics(self, **kwargs)

    def release_flux_network_distance_metrics(
        self,
        **kwargs,
    ) -> dict[str, float | int | str | None]:
        """Lazy raw planar distance metrics for direct release flux."""
        from hydromodpy.results import views

        return views.release_flux_network_distance_metrics(self, **kwargs)
