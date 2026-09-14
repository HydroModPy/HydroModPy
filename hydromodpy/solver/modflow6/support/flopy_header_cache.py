"""Cache FloPy MF6 block-header transient keys to break an O(nper^2) scan.

FloPy resolves every repeating block header through
``MFBlockHeader.get_transient_key``, which reads the header scalar back
through the whole MFData storage machinery. ``MFBlock.header_exists`` scans
all existing headers once per provided period, both at package construction
(``_build_repeating_header``) and again at write time
(``_add_missing_block_headers``), so transient packages cost O(nper^2)
storage reads. A 19-year daily chronicle (nper=6940) spends ~5 minutes in
this bookkeeping alone with flopy 3.10.0.

An integer transient key is write-once: ``build_header_variables`` binds it
when the header is created and nothing rebinds it afterwards (flopy only
renames string FILE keys, through ``MFTransient.update_transient_key``).
Caching the resolved integer on the header instance turns each scan step
into one attribute read, and the ``build_header_variables`` wrapper drops
the cache so a rebind can never serve a stale key. Calls passing
``data_path`` keep the original recursion-guard behaviour, and non-integer
keys are never cached.

Full analysis, benchmark, and upstream-PR notes:
``docs/_dev_notes/flopy_mf6_block_header_cache.md``. Remove this module once
the fix lands in a flopy release.
"""

from __future__ import annotations

import numpy as np
from flopy.mf6.mfpackage import MFBlockHeader

_PATCH_MARKER = "_hydromodpy_header_cache"
_CACHE_ATTR = "_hydromodpy_transient_key"


def install_flopy_header_cache() -> None:
    """Patch ``MFBlockHeader`` so integer transient keys resolve in O(1)."""
    if getattr(MFBlockHeader.get_transient_key, _PATCH_MARKER, False):
        return

    original_get = MFBlockHeader.get_transient_key
    original_build = MFBlockHeader.build_header_variables

    def get_transient_key(self, data_path=None):
        if data_path is not None:
            return original_get(self, data_path)
        cached = getattr(self, _CACHE_ATTR, None)
        if cached is not None:
            return cached
        key = original_get(self, None)
        # type() instead of isinstance(): bool is an int subclass, and True is
        # the recursion-guard sentinel, not a period key.
        if type(key) is int or isinstance(key, np.integer):
            setattr(self, _CACHE_ATTR, key)
        return key

    def build_header_variables(self, *args, **kwargs):
        if hasattr(self, _CACHE_ATTR):
            delattr(self, _CACHE_ATTR)
        return original_build(self, *args, **kwargs)

    setattr(get_transient_key, _PATCH_MARKER, True)
    MFBlockHeader.get_transient_key = get_transient_key
    MFBlockHeader.build_header_variables = build_header_variables
