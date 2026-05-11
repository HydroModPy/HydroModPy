"""Stream-network metric views.

Thin re-export of :func:`hydromodpy.results.views.cell_field_network_distance_metrics`
so that callers locating stream-network helpers under the analysis layer find them
at the expected path.
"""

from __future__ import annotations

from hydromodpy.results.views import cell_field_network_distance_metrics

__all__ = ["cell_field_network_distance_metrics"]
