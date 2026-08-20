"""Serialize the first FloPy MF6 DFN-structure load across threads.

``flopy.mf6.data.mfstructure.MFStructure`` is a lazy singleton whose
``__new__`` publishes the instance *before* ``_load()`` has filled
``sim_spec``. Two threads constructing an ``MFSimulation`` on a cold
process therefore race: the loser gets the published-but-empty instance,
every package structure lookup resolves to ``None``, and
``MFPackage.build_mfdata`` raises
``AttributeError: 'NoneType' object has no attribute 'blocks'``.

Parallel calibration builds one MF6 simulation per trial thread, so the
first concurrent cohort loses trials to this race (measured: 3 of 4
threads fail on a cold process). Building the singleton once under a lock,
before any thread reaches a flopy MF6 constructor, removes it. Remove this
module once the singleton is thread-safe upstream.
"""

from __future__ import annotations

import threading

_LOAD_LOCK = threading.Lock()


def warm_flopy_structure() -> None:
    """Build the FloPy MF6 DFN-structure singleton once, under a lock."""
    from flopy.mf6.data.mfstructure import MFStructure

    with _LOAD_LOCK:
        MFStructure()
