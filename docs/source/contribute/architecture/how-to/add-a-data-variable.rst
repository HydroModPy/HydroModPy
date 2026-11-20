Add a data variable
===================

A *data variable* is one ``[data.<name>]`` section of a project TOML, loaded
by one variable class and stored in the input cache. The variables that ship are listed
in :doc:`/reference/data-sources`.

Add a variable only for a new physical quantity with its own unit. A source of an existing
variable is :doc:`add-a-data-source`. The set is closed, because each variable is a field
of ``DataConfig`` that the JSON schema publishes, so it is a change of HydroModPy and not a
plugin.

Pick a base class
-----------------

- ``GridVariable`` for gridded data (``FieldRecord``): it caches grids as
  NetCDF and loads a user's NetCDF, GeoTIFF or folder of chronicles.
- ``StationVariable`` for station chronicles (``PointRecord``): it caches
  one file per station and asks a provider only for the missing periods.
- ``FileVariable`` for a variable read only from the user's own files.
  ``RasterFileVariable`` is its base for a single-band raster and needs only
  ``VARIABLE_NAME``.

All three live in ``hydromodpy/data/families/``. ``wind`` in ``sim2_series.py``
is the shortest grid variable to copy, ``hydrometry`` the shortest station variable.

A thin variable or a variable with its own folder
-------------------------------------------------

A thin variable has a source config, a section config and a variable class that
names itself, and no code of its own. It gets no folder. Its three classes join the flat
module of the family it looks like under ``hydromodpy/data/variables/``
(``sim2_series.py``, ``forcing_series.py``, ``lake_series.py`` or ``user_rasters.py``),
or open a new flat module when it starts a family. A variable that needs a provider
module, a resolver or a file loader of its own (``dem``, ``geology``, ``hydrography``,
``hydrometry``) takes a folder:

.. code-block:: text

   hydromodpy/data/variables/<name>/
   |-- __init__.py   a docstring, no import
   |-- config.py     <Name>SourceConfig, <Name>Config
   |-- variable.py   <Name>Variable: VARIABLE_NAME, INTERNAL_UNIT, SOURCES
   `-- apis/         one module per network provider, if the variable has one

A variable never imports another variable, and a family module imports none either
(``tests/unit/architecture/test_package_layouts.py`` checks both). A flat module
must be one that ``VARIABLE_SPECS`` names.

For a thin variable called ``evaporation``, these classes go into
``hydromodpy/data/variables/forcing_series.py``, next to ``etp`` and ``precipitation``.

.. code-block:: python

   class EvaporationSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
       """One evaporation source."""

       source: Annotated[Literal["file"], Profile.USER] = Field(
           ..., description="Data provider: 'file' for the user's files."
       )
       path: Annotated[str | None, Profile.USER] = Field(
           default=None, description="A .nc or .tif file, or a folder of chronicles."
       )


   class EvaporationConfig(BaseVariableConfig):
       """Top-level evaporation configuration."""

       _TOML_SECTION = "evaporation"

       sources: Annotated[list[EvaporationSourceConfig], Profile.USER] = Field(
           ..., min_length=1, description="At least one data source."
       )


   class EvaporationVariable(GridVariable):
       VARIABLE_NAME = "evaporation"
       INTERNAL_UNIT = "mm/day"
       SOURCES = {}

The base class handles ``file`` through ``load_file``. Each network provider adds one key
in ``SOURCES``, see :doc:`add-a-data-source`.

Contract
--------

Each variable is one row of ``VARIABLE_SPECS``. The row names the config and variable
classes as text, and holds the columns of the drop zone that ``hmp workspace init``
creates.

.. literalinclude:: /../../hydromodpy/data/loading/_dispatch.py
   :pyobject: VariableSpec

Register
--------

A variable joins these lists:

1. ``hydromodpy/data/loading/_dispatch.py``: a ``VariableSpec`` in ``VARIABLE_SPECS``.
2. ``hydromodpy/data/loading/config_schema.py``: a field of ``DataConfig``.
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

What the TOML says
------------------

.. code-block:: toml

   # not checked: evaporation is the placeholder variable of this recipe
   [data]
   types = ["evaporation"]

   [[data.evaporation.sources]]
   source = "file"
   path = "inputs/evaporation_basin.nc"

Test
----

``pytest tests/unit/architecture tests/unit/data -q`` runs the gates. Add:

- the config: a ``file`` source without ``path`` is refused;
- the variable class on a small fixture file, offline;
- each provider with a recorded answer, so the tier runs without network.

See also
--------

- :doc:`../packages/data` for the package map and the variable template.
- :doc:`add-a-data-source` for a source of an existing variable.
- :doc:`add-a-config-field` for a TOML knob outside the source list.
