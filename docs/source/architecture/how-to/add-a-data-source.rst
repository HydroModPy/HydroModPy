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

There is no source registry and no registration decorator. A source is
wired by two explicit edits inside its own variable package:

1. a new literal in the variable's discriminated source union
   (``hydromodpy/data/variables/<variable>/config.py``);
2. a new branch in the variable manager's ``_fetch_from_source``
   (``hydromodpy/data/variables/<variable>/manager.py``), which imports
   the adapter module lazily and calls its module-level ``fetch``.

The adapter itself is a plain module exposing a ``fetch`` function that
returns contract records:

.. code-block:: python

   # hydromodpy/data/variables/<variable>/apis/<source_name>.py
   def fetch(station_ids, start, end, ...) -> list[PointRecord]:
       ...

``source_cfg`` is the validated Pydantic block from
``[data.<variable>]``; the manager supplies the project period, the
workspace cache handle, and the geographic context when needed.

Public API source
-----------------

Pick this flavour for an HTTP backend (Hub'Eau, BRGM, BD TOPAGE,
SIM2, SHOM, IGN BD Alti, etc.).

.. code-block:: text

   hydromodpy/data/variables/<variable>/apis/<source_name>.py

Skeleton:

.. code-block:: python

   from hydromodpy.data.common.api_client import get_json
   from hydromodpy.data.contracts.timeseries import PointRecord


   API_BASE = "https://api.example.org/hydrometry"


   def fetch(station_ids, start, end) -> list[PointRecord]:
       payload = get_json(
           f"{API_BASE}/observations",
           params={"stations": ",".join(station_ids), "start": start, "end": end},
       )
       return [PointRecord(...) for entry in payload["data"]]

Use ``get_json`` (``hydromodpy/data/common/api_client.py``) or
``HTTPClient`` (``hydromodpy/core/io/http_client.py``) instead of raw
``requests``: they handle retry, backoff, timeout, and SHA-256
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

Custom sources need no extra wiring beyond the ``source == "custom"``
branch the manager already carries.

Synthetic source
----------------

Pick this flavour for generators (constant value, analytical
forcing, periodic chronicle). They live next to the variable's
custom loader and produce ``PointRecord`` or ``FieldRecord`` from
parameters declared in the TOML.

.. code-block:: python

   # hydromodpy/data/variables/recharge/synthetic.py
   def load_synthetic(source_cfg, project_period) -> list[PointRecord]:
       series = build_series(source_cfg.amplitude, source_cfg.period)
       return [PointRecord(...) for value in series]

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

   def _fetch_from_source(self, source_cfg):
       if source_cfg.source == "custom":
           return load_custom(source_cfg, self.project_period)
       if source_cfg.source == "mysource":
           from hydromodpy.data.variables.myvariable.apis.mysource import fetch

           return fetch(source_cfg.station_ids, self.start, self.end)
       raise ValueError(f"Unknown myvariable source: {source_cfg.source}")

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
