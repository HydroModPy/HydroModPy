Add a Data Variable
===================

A *data variable* is one ``[data.<name>]`` section of a project TOML, loaded
by one manager and stored in the input cache. Twenty-five ship under
``hydromodpy/data/variables/``; their single list is ``VARIABLE_SPECS`` in
``hydromodpy/data/loading/_dispatch.py``.

Add a variable only when the family is genuinely new: a new physical quantity
with its own unit. To add a **source** to an existing variable, see
:doc:`add-a-data-source` instead. The set of variables is closed on purpose:
each one is an explicit field of ``DataManagersConfig`` that the JSON schema
publishes, so a variable is a change of HydroModPy and not a plugin.

Pick a manager base
-------------------

- ``BaseFieldManager`` for gridded data (``FieldRecord``): it caches grids as
  NetCDF and loads a user's NetCDF, GeoTIFF or folder of chronicles.
- ``BaseVariableManager`` for station chronicles (``PointRecord``): it caches
  one file per station and asks a provider only for the missing periods.
- ``BaseFileManager`` for a variable read only from the user's own files
  (``lake_abacus``, ``lake_bathymetry``, ``lake_geometry``, ``substratum``).
  ``RasterFileManager``, in the same module, is the further-specialized base
  for a single-band raster read only from the user's own files
  (``lake_bathymetry``, ``substratum``): it needs only ``VARIABLE_NAME``.

All three live in ``hydromodpy/data/managers/``. ``wind`` is the shortest
grid variable to copy, ``hydrometry`` the shortest station variable.

The package
-----------

For a variable called ``evaporation``:

.. code-block:: text

   hydromodpy/data/variables/evaporation/
   |-- __init__.py   a docstring; importing the package loads no manager
   |-- config.py     EvaporationSourceConfig, EvaporationConfig
   |-- manager.py    EvaporationManager: VARIABLE_NAME, INTERNAL_UNIT, SOURCES
   `-- apis/         one module per network provider, if the variable has one

.. code-block:: python

   # hydromodpy/data/variables/evaporation/config.py
   from typing import Annotated, Literal

   from pydantic import Field

   from hydromodpy.core.config_kit.profile import Profile
   from hydromodpy.data.managers.base_config import BaseVariableConfig
   from hydromodpy.data.managers.timeseries_config import (
       TimeseriesColumnsMixin,
       TimeseriesSelectionMixin,
   )


   class EvaporationSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
       """One evaporation source."""

       source: Annotated[Literal["custom"], Profile.USER] = Field(
           ..., description="Data provider: 'custom' for the user's files."
       )
       path: Annotated[str | None, Profile.USER] = Field(
           default=None, description="A .nc or .tif file, or a folder of chronicles."
       )
       crs: Annotated[str | None, Profile.USER] = Field(
           default=None, description="CRS of a custom NetCDF that declares none."
       )
       nodata: Annotated[float | None, Profile.USER] = Field(
           default=None, description="Nodata of a custom NetCDF that declares none."
       )


   class EvaporationConfig(BaseVariableConfig):
       """Top-level evaporation configuration."""

       _TOML_SECTION = "evaporation"

       sources: Annotated[list[EvaporationSourceConfig], Profile.USER] = Field(
           ..., min_length=1, description="At least one data source."
       )

.. code-block:: python

   # hydromodpy/data/variables/evaporation/manager.py
   from hydromodpy.data.managers.base_manager_field import BaseFieldManager


   class EvaporationManager(BaseFieldManager):
       VARIABLE_NAME = "evaporation"
       INTERNAL_UNIT = "mm/day"
       SOURCES = {}

``custom`` is never in ``SOURCES``: the base class loads the user's files.
Each network provider adds one key, see :doc:`add-a-data-source`.

The lists a variable joins
--------------------------

1. ``hydromodpy/data/loading/_dispatch.py``: a ``VariableSpec`` in
   ``VARIABLE_SPECS`` naming the config and manager classes.
2. ``hydromodpy/data/loading/config_schema.py``: the name in
   ``SUPPORTED_DATA_MANAGER_TYPES``, a field of ``DataManagersConfig``, and
   the config class in ``_TYPED_SECTIONS`` and in ``_rebuild_forward_refs``.
3. ``hydromodpy/core/state/data.py``: a field of ``LoadedDataContext``.
4. ``hydromodpy/data/workspace/scaffold.py``: a ``VariableSpec`` in
   ``VARIABLES``, the drop zone ``hmp workspace init`` creates.
5. ``hydromodpy/_lazy.py``: ``EvaporationConfig`` and
   ``EvaporationSourceConfig``.
6. ``hydromodpy/schema/sources.py``: an entry (licence, network hosts) for
   each new provider slug.
7. The planner, only when the variable should be activated by another section
   (``hydromodpy/data/loading/planner.py``); otherwise the user lists it in
   ``[data].types``.

``tests/unit/data/test_the_variable_families_agree.py`` compares the lists to
``VARIABLE_SPECS`` and names the one you missed. Two pins move with a new
variable, and moving them is the point: the variable count in the same test,
and ``DATA_SCHEMA_SHA256`` in ``tests/unit/data/test_the_data_surfaces_hold_still.py``.
Regenerate the configuration reference with ``python -m tools.doc_config``.

Check it
--------

.. code-block:: toml

   [data]
   types = ["evaporation"]

   [[data.evaporation.sources]]
   source = "custom"
   path = "data/evaporation/evaporation_basin.nc"
   nodata = -9999.0

.. code-block:: console

   $ pytest tests/unit/architecture tests/unit/data -q
   $ cat > ask.json <<'JSON'
   {"data": {"evaporation": {"sources": [
      {"source": "custom", "path": "data/evaporation/evaporation_basin.nc",
       "nodata": -9999.0}]}},
    "extent": {"bbox": [320000, 6780000, 330000, 6790000], "crs": "EPSG:2154"},
    "period": {"start": "2020-01-01", "end": "2020-01-31"}}
   JSON
   $ hmp data get ask.json --out evap/

``hmp data get`` reads your file back through the new manager, cut to the box
and the period, into ``evap/evaporation_custom.nc`` beside ``evap/request.json``.
A job refuses a ``custom`` source; the command line serves it.

Tests to add
------------

- the config: a ``custom`` source without ``path`` is refused;
- the manager on a small fixture file, offline;
- each provider with a recorded answer, so the tier runs without network.

See also
--------

- :doc:`../packages/data` for the package map and the manager template.
- :doc:`add-a-data-source` for a source of an existing variable.
- :doc:`add-a-config-field` for a TOML knob outside the source list.
