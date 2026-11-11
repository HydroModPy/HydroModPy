"""The licence a run may state, derived from the inputs it read.

The inputs are the entries of ``inputs.json``. Each entry carries the licence
its own sidecar stated when the run read the file, and the run states the
roll-up of those licences. An entry with no licence, and a run with no entry
at all, give ``LicenseRef-undetermined``. The mesh a run seals beside itself
is a product of the run, not an input, so it adds no licence. A source that
reads no file (``constant``, ``synthetic``, a record built in memory) writes no
entry, so it adds no licence either. A run that reads a constant recharge and
one DEM under etalab-2.0 states etalab-2.0, where it used to state
``LicenseRef-undetermined``.
"""

from __future__ import annotations

from collections.abc import Iterable

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.results.record.manifest import InputEntry, sealed_in_run
from hydromodpy.schema.job.inputset import UNDETERMINED, Licence
from hydromodpy.schema.sources import derived_licence


def run_licence(entries: Iterable[InputEntry]) -> str:
    """Return the licence a run may state from the entries of its ``inputs.json``."""
    licences = [
        Licence(spdx=entry.license.strip())
        if entry.license and entry.license.strip()
        else UNDETERMINED
        for entry in entries
        if not sealed_in_run(entry)
    ]
    return derived_licence(licences) if licences else UNDETERMINED_LICENSE


__all__ = ["run_licence"]
