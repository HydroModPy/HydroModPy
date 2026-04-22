"""Superseded by ``tests/unit/test_storage_catalog.py`` (phase P02).

The pre-P02 schema had ``cell_types``, ``bbox DOUBLE[4]``, ``crs``,
``tags VARCHAR[]`` columns and a ``_schema_version`` table. The clean-slate
refactor removed them in favour of ``bbox_xmin/ymin/xmax/ymax``,
``crs_wkt``/``crs_epsg``, ``config_snapshot`` and
``geographic_fingerprint``. The assertions in this file targeted the old
layout and are no longer meaningful.

The equivalent coverage now lives in ``tests/unit/test_storage_catalog.py``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Obsolete post-P02 schema refactor. "
        "See tests/unit/test_storage_catalog.py."
    ),
)
