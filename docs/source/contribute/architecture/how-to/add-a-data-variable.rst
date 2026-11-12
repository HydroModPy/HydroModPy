Add a data variable
===================

A *data variable* is one ``[data.<name>]`` section of a project TOML, loaded
by one variable class and stored in the input cache. Twenty-eight ship under
``hydromodpy/data/variables/``; their single registry is ``VARIABLE_SPECS`` in
``hydromodpy/data/loading/_dispatch.py``.

Add a variable only when the family is genuinely new: a new physical quantity
with its own unit. To add a **source** to an existing variable, see
:doc:`add-a-data-source` instead. The set of variables is closed on purpose:
each one is an explicit field of ``DataConfig`` that the JSON schema
publishes, so a variable is a change of HydroModPy and not a plugin.

Pick a base class
-----------------

- ``GridVariable`` for gridded data (``FieldRecord``): it caches grids as
  NetCDF and loads a user's NetCDF, GeoTIFF or folder of chronicles.
- ``StationVariable`` for station chronicles (``PointRecord``): it caches
  one file per station and asks a provider only for the missing periods.
- ``FileVariable`` for a variable read only from the user's own files
  (``lake_abacus``, ``lake_bathymetry``, ``lake_geometry``, ``substratum``).
  ``RasterFileVariable``, in the same module, is the further-specialized base
  for a single-band raster read only from the user's own files
  (``lake_bathymetry``, ``substratum``): it needs only ``VARIABLE_NAME``.

All three live in ``hydromodpy/data/families/``. ``wind`` in ``sim2_series.py``
is the shortest grid variable to copy, ``hydrometry`` the shortest station
variable.

A thin variable or a variable with its own folder
-------------------------------------------------

A thin variable has a source config, a section config and a variable class that
names itself, and no code of its own. It gets no folder. Its three classes sit in
the flat module of its family under ``hydromodpy/data/variables/``:

.. code-block:: text

   sim2_series.py      wind, humidity, runoff, soil moisture, temperature
   forcing_series.py   radiation, ETP, precipitation
   lake_series.py      lake levels, inflow, outflow, withdrawal
   user_rasters.py     soil capacity, substratum, layer base

A new variable joins the module of the family it looks like, or opens a new flat
module when it starts a family. A variable that needs a provider module, a
resolver or a file loader of its own (``dem``, ``geology``, ``hydrography``,
``hydrometry``) takes a folder:

.. code-block:: text

   hydromodpy/data/variables/<name>/
   |-- __init__.py   a docstring, no import; importing the package loads nothing
   |-- config.py     <Name>SourceConfig, <Name>Config
   |-- variable.py   <Name>Variable: VARIABLE_NAME, INTERNAL_UNIT, SOURCES
   `-- apis/         one module per network provider, if the variable has one

A variable never imports another variable, and a family module imports none either
(``tests/unit/architecture/test_package_layouts.py`` checks both). A flat module
must be one that ``VARIABLE_SPECS`` names.

For a thin variable called ``evaporation``, these classes go into
``hydromodpy/data/variables/forcing_series.py``, next to ``etp`` and ``precipitation``.
The imports of that module already cover them.

.. code-block:: python

   # hydromodpy/data/variables/forcing_series.py
   from typing import Annotated, Literal

   from pydantic import Field

   from hydromodpy.core.config_kit.profile import Profile
   from hydromodpy.data.families.base_config import BaseVariableConfig
   from hydromodpy.data.families.grids import GridVariable
   from hydromodpy.data.families.timeseries_config import (
       TimeseriesColumnsMixin,
       TimeseriesSelectionMixin,
   )


   class EvaporationSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
       """One evaporation source."""

       source: Annotated[Literal["file"], Profile.USER] = Field(
           ..., description="Data provider: 'file' for the user's files."
       )
       path: Annotated[str | None, Profile.USER] = Field(
           default=None, description="A .nc or .tif file, or a folder of chronicles."
       )
       crs: Annotated[str | None, Profile.USER] = Field(
           default=None, description="CRS of a user NetCDF that declares none."
       )
       nodata: Annotated[float | None, Profile.USER] = Field(
           default=None, description="Nodata of a user NetCDF that declares none."
       )


   class EvaporationConfig(BaseVariableConfig):
       """Top-level evaporation configuration."""

       _TOML_SECTION = "evaporation"

       sources: Annotated[list[EvaporationSourceConfig], Profile.USER] = Field(
           ..., min_length=1, description="At least one data source."
       )

.. code-block:: python

   # the same module, after the config classes
   class EvaporationVariable(GridVariable):
       VARIABLE_NAME = "evaporation"
       INTERNAL_UNIT = "mm/day"
       SOURCES = {}

``file`` is handled by the base class through ``load_file``; each network
provider adds one key in ``SOURCES``, see :doc:`add-a-data-source`.

The lists a variable joins
--------------------------

1. ``hydromodpy/data/loading/_dispatch.py``: a ``VariableSpec`` in
   ``VARIABLE_SPECS`` naming the config and variable classes by their module as text.
   The same entry holds the columns of the drop zone ``hmp workspace init``
   creates (``category``, ``kind``, ``unit``, ``label``, and ``file_prefix`` when
   the token of the file names is not the variable name).
2. ``hydromodpy/data/loading/config_schema.py``: a field of ``DataConfig``.
   ``DATA_VARIABLES`` and the typed config class are read from ``VARIABLE_SPECS``.
3. ``hydromodpy/core/state/run_state.py``: a field of ``LoadedDataContext``.
4. ``hydromodpy/schema/sources.py``: an entry (licence, network hosts) for
   each new provider slug.
5. The planner, only when the variable should be activated by another section
   (``hydromodpy/data/loading/planner.py``); otherwise the user lists it in
   ``[data].types``.

``tests/unit/data/test_variable_families.py`` compares the lists to
``VARIABLE_SPECS`` and names the one you missed. Two pins move with a new
variable, and moving them is the point: the variable count in the same test,
and ``DATA_SCHEMA_SHA256`` in ``tests/unit/data/test_data_surfaces.py``.
The reference pages of the new section are written at the next documentation build.

Check it
--------

.. code-block:: toml

   # not checked: evaporation is the placeholder variable of this recipe
   [data]
   types = ["evaporation"]

   [[data.evaporation.sources]]
   source = "file"
   path = "inputs/evaporation_basin.nc"
   nodata = -9999.0

.. code-block:: console

   $ pytest tests/unit/architecture tests/unit/data -q
   $ cat > ask.json <<'JSON'
   {"data": {"evaporation": {"sources": [
      {"source": "file", "path": "inputs/evaporation_basin.nc",
       "nodata": -9999.0}]}},
    "extent": {"bbox": [320000, 6780000, 330000, 6790000], "crs": "EPSG:2154"},
    "period": {"start": "2020-01-01", "end": "2020-01-31"}}
   JSON
   $ hmp data get ask.json --to evap/

``hmp data get`` reads your file back through the new variable class, cut to the box
and the period, into ``evap/evaporation_file.nc`` beside ``evap/request.json``.
A job refuses a ``file`` source; the command line serves it.

Tests to add
------------

- the config: a ``file`` source without ``path`` is refused;
- the variable class on a small fixture file, offline;
- each provider with a recorded answer, so the tier runs without network.

See also
--------

- :doc:`../packages/data` for the package map and the variable template.
- :doc:`add-a-data-source` for a source of an existing variable.
- :doc:`add-a-config-field` for a TOML knob outside the source list.
