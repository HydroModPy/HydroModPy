"""``hmp.catalog`` -- input-data cache view for a workspace.

The simulation catalog itself is opened with :func:`hydromodpy.open`, which
returns a :class:`hydromodpy.results.catalog.Catalog`. This package
hosts the read-only view over the workspace data cache
(``<workspace>/data/cache.duckdb``).

Usage
-----

.. code-block:: python

    from hydromodpy.catalog import InputsNamespace

    inputs = InputsNamespace("~/ws")
    inputs.list(variable="recharge")
"""

from __future__ import annotations

from hydromodpy.catalog.inputs import InputsNamespace

__all__ = ["InputsNamespace"]
