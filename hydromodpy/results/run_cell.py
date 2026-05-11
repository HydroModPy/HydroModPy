"""Per-cell catchment views for :class:`hydromodpy.results.run.Run`.

Mixin that delegates lazy per-cell metrics (saturation, drainage density,
persistence, network overlap and distance for arbitrary cell fields) to
:mod:`hydromodpy.results.views`. Mixed into :class:`Run`; ``self`` is the
:class:`Run` instance the views consume.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class RunCellMixin:
    """Per-cell view delegators mixed into :class:`Run`."""

    def saturated_fraction(self, **kwargs) -> pd.Series:
        """Lazy % of catchment cells with saturated head."""
        from hydromodpy.results import views

        return views.saturated_fraction(self, **kwargs)

    def drainage_density(self, **kwargs) -> pd.Series:
        """Lazy % of catchment cells with positive routed drain flux."""
        from hydromodpy.results import views

        return views.drainage_density(self, **kwargs)

    def persistence(self, **kwargs) -> np.ndarray:
        """Lazy per-cell fraction of timesteps above a threshold."""
        from hydromodpy.results import views

        return views.persistence(self, **kwargs)

    def cell_field_active_mask(self, **kwargs) -> np.ndarray:
        """Lazy per-cell active mask for any scalar cell field."""
        from hydromodpy.results import views

        return views.cell_field_active_mask(self, **kwargs)

    def cell_field_active_metrics(self, **kwargs) -> dict[str, float | int | str]:
        """Lazy scalar active-cell metrics for any scalar cell field."""
        from hydromodpy.results import views

        return views.cell_field_active_metrics(self, **kwargs)

    def cell_field_network_overlap_metrics(self, **kwargs) -> dict[str, float | int | str]:
        """Lazy cell-overlap metrics for any active cell field against a network."""
        from hydromodpy.results import views

        return views.cell_field_network_overlap_metrics(self, **kwargs)

    def cell_field_network_distance_metrics(
        self,
        **kwargs,
    ) -> dict[str, float | int | str | None]:
        """Lazy planar distance metrics for any active cell field against a network."""
        from hydromodpy.results import views

        return views.cell_field_network_distance_metrics(self, **kwargs)

    def catchment_mean(self, variable: str, **kwargs) -> pd.Series:
        """Lazy arithmetic mean of a cell variable over active cells."""
        from hydromodpy.results import views

        return views.catchment_mean(self, variable, **kwargs)
