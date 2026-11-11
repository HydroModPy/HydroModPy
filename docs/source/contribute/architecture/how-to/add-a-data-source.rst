Add a data source
=================

A *source* is one value a user may write in ``source =`` for an existing
variable: a public API, the user's own files (``file``), a remote file
(``url``), or a generator (``constant``, ``synthetic``). For a brand-new
variable family, see :doc:`add-a-data-variable` first.

One form, in tree or out
------------------------

Every source is one class of the ``DataSource`` port
(``hydromodpy/data/source/port.py``), whatever it serves: the three river
networks, Hub'Eau, SIM2, Explore2, the IGN DEM, the two BRGM products, the
SHOM, BD TOPO, ROE and the two computed sources are classes of the port, the
same as a third-party plugin. The contract of the port, member by member, is
``hydromodpy/data/source/README.md``. The ports of every layer share the recipe of
:doc:`plug-into-a-port`.

An in-tree provider
-------------------

Four edits, three inside the variable's package and one in the registry:

1. the provider class, ``variables/<variable>/apis/<provider>.py`` (or
   ``common/clients/`` when several variables share it, as SIM2 does;
   a computed source lives in the module named after its value, as
   ``recharge/synthetic.py`` does);
2. the entry in ``_BUILTIN_PATHS`` of ``data/source/registry.py``, a
   dotted path, joined to the section and the class name;
3. the ``source`` field of ``variables/<variable>/config.py``, a string
   the config validates against ``data_sources.names(section)``;
4. an entry (licence, network hosts) in ``hydromodpy/schema/sources.py``.

A source class declares its section and its name, both ``ClassVar``:

.. code-block:: python

   # hydromodpy/data/variables/hydrometry/apis/acme.py
   from typing import ClassVar

   from hydromodpy.data.source.port import (
       Extent,
       FetchRequest,
       FetchResult,
       PayloadKind,
       PeriodNeed,
       Selector,
       extent_for,
       require_period,
       require_selectors,
   )


   class AcmeGauges:
       source_id: ClassVar[str] = "acme"
       section: ClassVar[str] = "hydrometry"
       payload_kind: ClassVar[PayloadKind] = "points"
       extent_crs: ClassVar[str] = "EPSG:4326"
       selectors: ClassVar[tuple[Selector, ...]] = ("extent", "station_ids")
       period_need: ClassVar[PeriodNeed] = "required"
       writes_out_dir: ClassVar[bool] = False

       def __init__(self, *, max_stations: int | None = None) -> None:
           self.max_stations = max_stations
           self.variables: tuple[str, ...] = ("discharge",)
           self.hosts: tuple[str, ...] = ("gauges.acme.example",)

       def fetch(self, request: FetchRequest) -> FetchResult:
           require_selectors(self, request)
           period = require_period(self, request)
           extent = extent_for(self, request)  # converted into extent_crs
           ...

``section`` is the ``[data.<section>]`` the class serves, one only. The
constructor carries what varies between two sources of one provider: its
parameters are the fields of the source section, bound by
``build_from_section``, exactly as a solver backend binds the fields of
``[solver.<name>]``. A source configured one way may serve fewer variables
than the class can, so ``variables`` belongs to the instance, and the hosts
it contacts belong to the instance too. A shipped source reads its hosts
from ``hydromodpy/schema/sources.py`` through ``shipped_hosts`` and writes
none itself, so a host is named once.

The request and the result
--------------------------

A ``FetchRequest`` carries an ``out_dir`` the source owns alone, an
``Extent`` (a bounding box and the CRS it is expressed in), ``station_ids``
and a ``Period``. A request with neither an extent nor stations is accepted
only from a source that declares ``selectors = ()``, and
``require_selectors`` enforces that: a URL or a local file service, a
constant or a synthetic series have nothing to ask for. Do not declare a
selector the fetch does not read.

A ``FetchResult`` carries ``points`` or ``fields`` records, or ``files`` as
``FileRecord`` entries (``path``, ``sha256``, ``state``, ``nodata``,
``origin``, built by ``FileRecord.of``, which hashes the file for the seal;
``state`` is ``"raw"`` or ``"conditioned"``, the vocabulary of
``schema/job/inputset.py``). Each record carries the unit its provider
answers in: the port converts no value, and the SI is reached at the entry
of the Model, where ``core/units`` converts and refuses a unit it cannot
read. A source that answers in a unit ``core/units`` cannot read yet is
allowed, and its ``SourceCase`` pins the unit it writes today.

A source must **not** know the DuckDB catalog, the project workspace, a
lock or a cache. The variable builds the request (a family of
stations from the station list or the extent, a family of grids from the
project extent) and owns the cache: ``GridVariable`` keeps grids,
``StationVariable`` keeps chronicles per station and asks only for the
missing periods. Use ``get_json`` (``hydromodpy/data/common/api_client.py``)
or ``open_client`` / ``HTTPClient`` (``hydromodpy/core/io/fetch.py``) rather
than raw ``requests``: they handle retry, backoff, host guards, byte caps and
timeout.

The section is usually **one flat model**: the fields of every source sit side
by side and ``source`` selects which are read, so a field name is never
reused across two sources of one variable. ``dem``, ``geology`` and
``crossings`` keep a discriminated union, each source carrying its own
model of options, with labels strictly matching ``data_sources.names(section)``
including ``file`` and ``url``. A module that holds a ``DataSource`` class
imports geopandas, pandas, rasterio or requests inside its functions, so
looking a source up loads nothing heavy.

``tests/unit/data/test_the_variable_families_agree.py`` checks that the
``source`` values of each variable match what the registry serves, and that
each has an entry in ``schema/sources.py``; a missing edit fails there with
the file to complete. ``value_docs`` renders the explanation of each value
on the card of the key, at the next documentation build.

User files, URLs and generators
-------------------------------

``source = "file"`` reads the user's files from disk. It is implemented by
``FileSource`` in ``hydromodpy/data/source/file.py`` and registered under
each section. It declares ``payload_kind = "files"`` and ``selectors = ()``,
reads files from paths relative to the project root (preferably under
``inputs/``), computes their SHA-256 for run identity, and writes nothing to
the cache.

``source = "url"`` downloads a single remote file to fill the local data
cache through ``hydromodpy.core.io.fetch``, recording origin, SHA-256,
and HTTP headers in a sidecar. It supports HTTPS, or HTTP with a pinned
``sha256`` checksum.

A generator is a source like any other, in the module named after its value
(``recharge/synthetic.py``, ``oceanic/constant.py``), and declares
``selectors = ()``, because it asks for neither an extent nor stations.

A plugin source
---------------

Publish it from your own distribution. The entry-point name is
``<section>_<source_id>``, the rule the solver backends follow:

.. code-block:: toml

   # your package's pyproject.toml
   [project.entry-points."hydromodpy.data.source"]
   hydrometry_acme = "mypackage.acme_gauges:AcmeGauges"

A plugin that fails any check is skipped with a warning naming what is
wrong, never raised: one broken plugin must not take down a host that asked
for a different source. The registry verifies the name against the section
and the ``source_id`` of the class it loads, without cutting the string, so
two sections whose names share a prefix are safe. A name this build already
ships under the same section is refused.

Name it from a document
-----------------------

.. code-block:: toml

   # not checked: acme is the placeholder source of this recipe
   # A project TOML. The section names a source of its own section; a source
   # of another section is refused, because the key is the pair of both.
   [[data.hydrometry.sources]]
   source = "acme"

.. code-block:: json

   {
     "process": {"id": "data-request", "version": "1.0.0"},
     "inputs": {
       "installed": [{"name": "acme", "options": {"max_stations": 5}}],
       "extent": {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"},
       "period": {"start": "2020-01-01", "end": "2020-01-31"}
     }
   }

Under ``installed``, a source resolves by its name alone, whatever its
section: a name two sections share is refused with both keys, so say
which one you mean. ``options`` is handed to the constructor as keyword
arguments and bound against its signature before anything runs, so an
argument the source cannot take is refused by name. An installed source does
not appear in the process description, which ships frozen in the wheel, and
the hosts it reaches are not declared there; ``outputs/request.json`` names
the source of each file the run wrote, in the unit the records carry.

Tests to add
------------

- the config: a source name the section refuses (a name of another section,
  an unknown name), a field that belongs to another source;
- the provider on a recorded answer, so the tier runs offline;
- a ``SourceCase`` describing which function your source calls, in your clone
  of this repository. The contract suite,
  ``tests/ports/test_data_source.py``, runs its declarations and
  its refusals on every source the registry serves, whether it ships or is
  installed, and the rest of the suite reads what the ``SourceCase`` says:
  the CRS the provider is really asked in, whether ``out_dir`` is left
  alone. To run it, install your distribution in a clone of this repository:
  the suite is not in the wheel.

See also
--------

- :doc:`../packages/data` for the variable inventory and the variable template.
- :doc:`add-a-data-variable` for a new variable family.
- :doc:`add-a-config-field` for a new field on an existing source.
- :doc:`/reference/data-sources` for the generated catalog of providers.
- :doc:`add-a-process` for exposing work as a capability an orchestrator runs,
  which is what ``data-request`` is.
