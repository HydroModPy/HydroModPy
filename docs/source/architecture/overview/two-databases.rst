The two workspace databases
===========================

A HydroModPy workspace carries two DuckDB databases with symmetric APIs:

Input cache - ``workspace/data/cache.duckdb``
---------------------------------------------

Tracks downloaded or custom datasets. Exposed through:

- ``DataCatalogDuckDB`` (low-level)
- ``DataStore`` (facade)
- ``DataEntry`` (view on one row)
- ``project.data`` / ``workspace.data`` accessors

Output catalog - ``workspace/hydromodpy.duckdb``
------------------------------------------------

Holds the simulation metadata, parameters, metrics, provenance, and
calibration history. It is scoped to the workspace, not to one simulation.
Each simulation gets a row in this catalog plus per-simulation Zarr/Parquet
artefacts under ``workspace/simulations/``. Exposed through:

- :class:`~hydromodpy.results.catalog.SimulationCatalog`
- :class:`~hydromodpy.results.run.Run`
- :class:`~hydromodpy.results.simulation_group.SimulationGroup`
- ``project.runs`` / ``workspace.runs`` accessors

Provenance bridge
-----------------

Each simulation records, in its ``provenance`` rows, which input-cache
entries it consumed. ``run.input_entries()`` walks the bridge to list
them, and ``entry.used_by()`` returns the simulations that referenced a
given entry.
