"""Every series the LAK extractor writes is a name ``[[export]]`` and ``hmp export`` know.

``outlet_inflow`` (what a lake receives from another lake's outlets) and the
flow through the cutoff wall were written by the extractor but missing from
the export vocabulary, so the step 0 check refused them as a typo.
"""

from __future__ import annotations

from hydromodpy.core.config_kit.export_spec import ExportKind
from hydromodpy.results.exporters.vocabulary import SIMULATED_SERIES, export_kind
from hydromodpy.solver.modflow6.extractors import lake as lake_extractor


def test_every_lake_series_is_a_simulated_series() -> None:
    written = (
        lake_extractor._STATE_QUANTITIES
        | lake_extractor._RATE_QUANTITIES
        | {lake_extractor.CUTOFF_WALL_FLOW}
    ) - {"lak_connection"}
    assert written - set(SIMULATED_SERIES) == set()
    assert export_kind("outlet_inflow") is ExportKind.series
    assert export_kind("cutoff_wall_flow") is ExportKind.series
    assert export_kind("seepage_under_dam") is None
