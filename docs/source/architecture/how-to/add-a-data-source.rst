Add a Data Source
=================

A *source* is a concrete origin (public API, custom file, synthetic
generator, or constant) bound to an existing data variable such as
``hydrometry``, ``geology``, ``dem``, or ``recharge``. This page
covers the three flavours.

For a brand-new variable family, see :doc:`add-a-data-variable`
first.

Source contract
---------------

Every source registers itself through
``hydromodpy/data/sources.py`` with the ``@register_source``
decorator:

.. code-block:: python

   from hydromodpy.data.sources import register_source


   @register_source(variable_type="hydrometry", source_name="mysource")
   class MySource:
       def fetch(self, source_cfg, context) -> "LoadResult":
           ...

The minimal Protocol exposes:

- ``variable_type`` (class attribute or decorator argument);
- ``source_name`` (class attribute or decorator argument);
- ``fetch(source_cfg, context) -> LoadResult``.

``source_cfg`` is the validated Pydantic block from
``[[data.<variable>.sources]]``; ``context`` carries the project
period, the workspace cache handle, and the geographic context when
needed.

Public API source
-----------------

Pick this flavour for an HTTP backend (Hub'Eau, BRGM, BD TOPAGE,
SIM2, SHOM, IGN BD Alti, etc.).

.. code-block:: text

   hydromodpy/data/variables/<variable>/apis/<source_name>.py

Skeleton:

.. code-block:: python

   from hydromodpy.core.io import HTTPClient, json_loads
   from hydromodpy.data.contracts.records import PointRecord
   from hydromodpy.data.contracts.results import LoadResult
   from hydromodpy.data.sources import register_source


   @register_source(variable_type="hydrometry", source_name="mysource")
   class MyHydrometrySource:
       def fetch(self, source_cfg, context) -> LoadResult:
           client = HTTPClient.get_default()
           response = client.get(
               "https://api.example.org/hydrometry",
               params={"product": source_cfg.product, "extent": "watershed"},
               timeout=30,
           )
           payload = json_loads(response.text)
           records = [PointRecord(...) for entry in payload["data"]]
           return LoadResult(points=records, fields=[], warnings=[])

Use ``HTTPClient`` (``hydromodpy/core/io/http_client.py``) instead of
raw ``requests``: it handles retry, backoff, timeout, and SHA-256
streaming.

Cache integrity goes through ``DataCatalogDuckDB``: every fetched
file is recorded with its path, mtime, and SHA-256 so future runs
can detect external modifications.

Custom-file source
------------------

Pick this flavour for local rasters, vectors, or CSV time series.
Convention is one ``custom.py`` per variable that knows how to read
the supported formats.

.. code-block:: python

   # hydromodpy/data/variables/<variable>/custom.py
   def load_custom(source_cfg, project_period) -> LoadResult:
       path = source_cfg.path
       # parse CSV / NetCDF / shapefile / GeoTIFF
       return LoadResult(points=[...], fields=[...], warnings=[...])

Custom sources usually do not register through ``@register_source``
because they are dispatched directly by the manager (``source ==
"custom"`` branch).

Synthetic source
----------------

Pick this flavour for generators (constant value, analytical
forcing, periodic chronicle). They live next to the variable's
custom loader and produce ``PointRecord`` or ``FieldRecord`` from
parameters declared in the TOML.

.. code-block:: python

   # hydromodpy/data/variables/recharge/synthetic.py
   @register_source(variable_type="recharge", source_name="synthetic")
   class SyntheticRecharge:
       def fetch(self, source_cfg, context) -> LoadResult:
           series = build_series(source_cfg.amplitude, source_cfg.period)
           return LoadResult(points=[...], fields=[...], warnings=[])

Wire the source config
----------------------

Add the new branch to the variable's discriminated source union:

.. code-block:: python

   # hydromodpy/data/variables/<variable>/config.py
   class MyApiSourceConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")
       source: Literal["mysource"]
       product: Annotated[str, Profile.USER]

   <Variable>SourceConfig = (
       <Variable>CustomSourceConfig
       | MyApiSourceConfig
       | ... existing branches ...
   )

The discriminated union ensures ``source = "mysource"`` cannot be
accepted with the wrong fields.

Wire the source into the manager
--------------------------------

Most variable managers dispatch on ``source_cfg.source`` inside
``_fetch_from_source``. Add the new branch:

.. code-block:: python

   def _fetch_from_source(self, source_cfg, project_period):
       if source_cfg.source == "custom":
           return load_custom(source_cfg, project_period)
       if source_cfg.source == "mysource":
           return get_source(self.VARIABLE_NAME, "mysource").fetch(
               source_cfg, project_period
           )
       raise ValueError(f"unknown source {source_cfg.source!r}")

Provenance
----------

The base manager records, in the catalog ``provenance`` table, the
``source_type`` (``http_api``, ``custom_file``, ``synthetic``,
``cache``, ``derived``) plus the source reference, the SHA-256 of
the fetched payload, and the fetch timestamp. Make sure your source
populates the fields the runtime expects.

Tests to add
------------

- **Unit** under ``tests/unit/data/<variable>/`` for the config
  branch (extra fields rejected, units parsed) and a fixture-backed
  ``fetch`` call.
- **Replay**: drop a static fixture under
  ``hydromodpy/data/variables/<variable>/examples/`` for the public
  source and a smoke test that loads it offline.
- **Integration** under ``tests/integration/data/`` if the new
  source changes how the planner infers active variables.

Pitfalls flagged by the layer matrix
------------------------------------

- ``data`` may not import ``simulation``, ``solver``, ``results``,
  ``display``, ``analysis``, ``calibration``, or ``workflow``.
- Do not call the network outside the source's ``fetch`` method:
  the cache layer expects deterministic, idempotent fetches.
- Keep the source layer free of physics and geographic logic. If
  your source needs reprojection or clipping, push the work back
  into ``hydromodpy/spatial/`` or ``core/io/`` helpers.

See also
--------

- :doc:`../packages/data` for the variable inventory and the manager
  contract.
- :doc:`add-a-data-variable` for adding a new variable family.
- :doc:`add-a-config-field` for adding a new field on an existing
  source.
- :doc:`/user_guide/data/index` for the user-facing inventory and
  provider matrix.
