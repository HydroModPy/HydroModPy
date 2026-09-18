Add a Data Source
=================

A *source* is a concrete origin (public API, custom file, synthetic
generator, or constant) bound to an existing data variable such as
``hydrometry``, ``geology``, ``dem``, or ``recharge``. This page
covers the three flavours.

For a brand-new variable family, see :doc:`add-a-data-variable`
first.

Two paths, and which one you are on
-----------------------------------

**The port.** ``hydromodpy/data/source/port.py`` declares what a source
owes its callers, and ``hydromodpy/data/source/registry.py`` resolves a
``source_id`` to the class that implements it. A source on this path is
reachable by name from a project TOML, from a ``data-fetch``
``request.json``, and from a third-party distribution that never patches
this repository. **It is the only path available out of tree.**

**The per-variable adapter.** Most variables still carry a module-level
``fetch`` under ``variables/<variable>/apis/`` and a branch on
``source_cfg.source`` in their manager's ``_fetch_from_source``.
Twenty-three variable packages still carry a closed ``Literal`` of source
names; ``hydrography`` is not one of them, and is the worked example of
what the port replaces it with.

Pick the port for anything new. The section below describes the adapter
path because it is what you will find when you read an unmigrated
variable, not because it is where a new source belongs.

The port
--------

Eight members, seven of them class-level declarations read *before* any
fetch runs, and one ``fetch``:

.. code-block:: python

   # mypackage/acme_radar.py
   from typing import ClassVar

   from hydromodpy.data.source.port import (
       FetchRequest,
       FetchResult,
       PayloadKind,
       PeriodNeed,
       Selector,
       extent_for,
   )


   class AcmeRadarSource:
       source_id: ClassVar[str] = "acme-radar"
       payload_kind: ClassVar[PayloadKind] = "fields"
       extent_crs: ClassVar[str] = "EPSG:3035"
       selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
       period_need: ClassVar[PeriodNeed] = "required"
       hosts: ClassVar[tuple[str, ...]] = ("radar.acme.example",)
       writes_out_dir: ClassVar[bool] = False

       def __init__(self, *, sweep: str = "long") -> None:
           self.sweep = sweep
           self.variables: tuple[str, ...] = ("radar_rainfall",)

       def fetch(self, request: FetchRequest) -> FetchResult:
           extent = extent_for(self, request)  # converts into extent_crs
           ...

``variables`` is the instance's and not the class's, because a source
configured one way may serve fewer variables than the class can.
Everything else is a ``ClassVar``, so the registry can refuse a
non-conforming class at registration instead of mid-fetch.

What a source must **not** know: the DuckDB catalogue, the project
workspace, the ``geographic`` object, a lock, or a cache. It receives an
``Extent`` carrying its own CRS, an optional ``Period``, and an
``out_dir`` scratch it owns alone. Anything it writes outside ``out_dir``
is a bug the conformance suite catches.

Register it
-----------

In tree, add one line to ``_BUILTIN_PATHS`` in
``hydromodpy/data/source/registry.py``:

.. code-block:: python

   "acme-radar": "hydromodpy.data.source.acme_radar:AcmeRadarSource",

Nothing else. There is deliberately no ``[project.entry-points]`` table
for in-tree sources: a second declaration is a second name, and that is
how the solver registry once minted a backend with an adapter and no
extractor.

Out of tree, publish the class on the ``hydromodpy.data.source``
entry-point group, from your own distribution:

.. code-block:: toml

   # your package's pyproject.toml
   [project.entry-points."hydromodpy.data.source"]
   acme-radar = "mypackage.acme_radar:AcmeRadarSource"

The entry-point name must equal the ``source_id`` the class declares --
a request writes the name and a result is stamped with the ``source_id``,
and two words for one source is how the two start disagreeing. A name
this build already ships is refused, because the published description of
``data-fetch`` names it and publishes the shape the in-tree adapter
accepts. A plugin that fails any of these checks is skipped with a
warning naming what is wrong, never raised: one broken plugin must not
take down a host that asked for a different source.

Name it from a document
-----------------------

Once registered, the id is nameable without any further edit here:

.. code-block:: toml

   # a project TOML. The section names a source whose payload kind is
   # "features"; a source of another kind is refused by the document.
   [[data.hydrography.sources]]
   source = "acme-linework"

.. code-block:: json

   {
     "process": {"id": "data-fetch", "version": "1.0.0"},
     "inputs": {
       "source": {"id": "installed", "name": "acme-radar",
                  "options": {"sweep": "short"}},
       "extent": {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}
     }
   }

The ``installed`` member of ``data-fetch`` is for sources this build does
not describe. The four it does describe have a member of their own, with
the exact shape they accept published in
``hydromodpy/schema/processes/data-fetch@1.json``; naming one through
``installed`` is refused. ``options`` is handed to the constructor as
keyword arguments and bound against its signature before the job starts,
so an argument the source cannot take is refused by name rather than
raised mid-fetch.

Two things the description cannot say about an installed source, and
both are by design: it does not appear in the process description, which
ships frozen in the wheel, and the hosts it reaches are not in
``hmp:invocation.network``. ``outputs/fetch.json`` records the hosts the
run really contacted.

A configuration section binds by parameter name
-----------------------------------------------

A variable section such as ``[[data.hydrography.sources]]`` is flat and
shared by every source it can name, so the binder hands a source **the
section field its constructor names, and nothing else**. Declare your
parameters with the names the section uses and you receive them; declare
a name the section does not carry and you get your own default. A
positional-only parameter without a default is refused, because a
section fills a parameter by name.

Full configuration of an out-of-tree source is the ``data-fetch``
capability's job, where the request document carries an explicit
``options`` object instead of a shared flat section.

Conformance
-----------

``tests/contract/test_data_source_contract.py`` runs every declaration
against a real fetch: the payload kind it claims, the CRS the provider is
really asked in, whether a period is really required, and whether
``out_dir`` is really left alone. Add your source to that parametrisation
when it lands in tree.

The adapter path, for the variables still on it
-----------------------------------------------

A source on this path is wired by two explicit edits inside its own
variable package:

1. a new member in the variable's ``source`` field
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

A variable's source section is **one flat model**, not a discriminated
union of one model per source: every source's fields sit side by side and
``source`` selects which of them are read. Add the literal and the fields
your source needs:

.. code-block:: python

   # hydromodpy/data/variables/<variable>/config.py
   class MyVariableSourceConfig(HydroModelBase):
       source: Annotated[Literal["custom", "mysource"], Profile.USER] = Field(
           ...,
           description="Data provider.",
           json_schema_extra={"value_docs": {"mysource": "what it downloads."}},
       )
       product: Annotated[str, Profile.DEV] = Field(default="level", description="...")

``extra="forbid"`` comes from ``HydroModelBase``, so an unknown key is
refused; a field that belongs to another source of the same section is
not, which is the price of the flat shape and the reason a field name is
never reused across two sources of one variable.

``value_docs`` is what renders the per-value table in the configuration
reference. A user-facing choice field without it is reported by
``python -m tools.doc_config``.

A variable on the port has no literal to extend: ``source`` is a plain
``str`` validated against the registry, and the payload kind the variable
accepts is checked at the same time, so naming a DEM source in a river
section is refused by the document.

Wire the source into the manager
--------------------------------

A variable still on the adapter path dispatches on ``source_cfg.source``
inside ``_fetch_from_source``. Add the new branch:

.. code-block:: python

   def _fetch_from_source(self, source_cfg):
       if source_cfg.source == "custom":
           return load_custom(source_cfg, self.project_period)
       if source_cfg.source == "mysource":
           from hydromodpy.data.variables.myvariable.apis.mysource import fetch

           return fetch(source_cfg.station_ids, self.start, self.end)
       raise ValueError(f"Unknown myvariable source: {source_cfg.source}")

A variable on the port has no such chain.
``hydromodpy/data/variables/hydrography/manager.py`` keeps one branch for
``custom``, which reads a local file and contacts nobody, and hands every
other name to ``source_from_section``. Read that method before adding a
branch here.

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
- **Integration** under ``tests/integration/data_managers/`` if the new
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
- :doc:`add-a-process` for exposing work as a capability an orchestrator
  runs, which is what ``data-fetch`` is.
