"""HydroModPy's own RuntimeWarnings reach the log while flopy silences them.

``flopy.plot.plotutil`` runs ``warnings.simplefilter("ignore", RuntimeWarning)``
at import, so in a run ``warnings.warn`` alone shows nothing. The lake bed
reconcile stands for every such warning: it logs the message as well.
"""

from __future__ import annotations

import logging
import warnings

from hydromodpy.spatial.lake_bed.reconcile import reconcile_bed_to_abacus


def test_the_message_is_logged_when_runtime_warnings_are_ignored(caplog):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with caplog.at_level(logging.WARNING):
            reconcile_bed_to_abacus(
                bed_by_cell={0: 90.0, 1: 91.0},
                area_by_cell={0: 100.0, 1: 100.0},
                abacus_stage=[90.0, 92.0],
                abacus_sarea=[50.0, 100.0],
            )
    assert "departs from the abacus full-pool area" in caplog.text
