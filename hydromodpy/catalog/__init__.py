"""High-level catalog facade that hides the three V1 DuckDB files.

V1 ships three physical DuckDB files (per-workspace cache, per-project
catalog, machine-wide index). This module wraps them behind three
read-mostly namespaces so end-user code never has to know which file
holds which row.

Usage
-----

.. code-block:: python

    import hydromodpy as hmp

    cat = hmp.catalog(workspace="~/proj/naizin")
    cat.simulations.find(solver="modflow6")
    cat.inputs.list(variable="recharge")
    cat.projects.list()

``cat`` is a :class:`CatalogFacade` -- the entrypoint also accepts
``hmp.catalog.simulations``/``inputs``/``projects`` directly when the
``HMP_WORKSPACE`` env var is set.
"""

from __future__ import annotations

from hydromodpy.catalog.facade import CatalogFacade, open_catalog
from hydromodpy.catalog.inputs import InputsNamespace
from hydromodpy.catalog.projects import ProjectsNamespace
from hydromodpy.catalog.simulations import SimulationsNamespace

__all__ = [
    "CatalogFacade",
    "InputsNamespace",
    "ProjectsNamespace",
    "SimulationsNamespace",
    "open_catalog",
]
