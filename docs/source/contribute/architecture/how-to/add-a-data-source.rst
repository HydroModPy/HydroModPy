Add a data source
=================

A *source* is one value a user may write in ``source =`` for an existing variable.
It can be a public API, the user's own files (``file``), a remote file (``url``) or a
generator (``constant``, ``synthetic``). For a brand-new variable family, see
:doc:`add-a-data-variable` first. The shipped providers are listed on
:doc:`/reference/data-sources`.

Every source is one class of the ``DataSource`` port, whatever it serves. A shipped
provider and a third-party plugin have the same form. The contract of the port, member
by member, is ``hydromodpy/data/source/README.md``, and the Protocol is
``DataSource`` in ``hydromodpy/data/source/port.py``.

Files to create
---------------

Four edits, three inside the package of the variable and one in the registry.

1. The provider class, ``variables/<variable>/apis/<provider>.py``. Use
   ``common/clients/`` when several variables share the provider, as SIM2 does. A
   computed source lives in the module named after its value, as
   ``recharge/synthetic.py`` does.
2. The ``source`` field of ``variables/<variable>/config.py``. The config validates it
   against ``data_sources.names(section)``.
3. An entry (licence, network hosts) in ``hydromodpy/schema/sources.py``.
4. The registration, below.

Contract
--------

A source class declares its section and its name as ``ClassVar``. Here is the minimal
skeleton.

.. code-block:: python

   # hydromodpy/data/variables/hydrometry/apis/acme.py
   from typing import ClassVar

   from hydromodpy.data.source.port import (
       FetchRequest, FetchResult, PayloadKind, PeriodNeed, Selector,
       extent_for, require_period, require_selectors,
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

``section`` is the one ``[data.<section>]`` the class serves. The constructor carries
what varies between two sources of one provider. Its parameters are the fields of the
source section, bound by ``build_from_section``. A source configured one way may serve
fewer variables than the class can, so ``variables`` and ``hosts`` belong to the
instance. A shipped source reads its hosts from ``hydromodpy/schema/sources.py`` through
``shipped_hosts``, so a host is named once.

A ``FetchRequest`` carries an ``out_dir`` that the source owns alone, an ``Extent``,
``station_ids`` and a ``Period``. A request with neither an extent nor stations is
accepted only from a source that declares ``selectors = ()``, as a URL, a local file, a
constant or a synthetic series do. Do not declare a selector that the fetch does not
read. A ``FetchResult`` carries ``points`` or ``fields`` records, or ``files`` as
``FileRecord`` entries built by ``FileRecord.of``, which hashes the file for the seal.
Each record carries the unit its provider answers in. The port converts no value, and
``core/units`` converts to SI at the entry of the ``Model``.

A source must not know the DuckDB catalog, the project workspace, a lock or a cache.
The variable builds the request and owns the cache. For HTTP, use ``get_json``
(``hydromodpy/data/common/api_client.py``) or ``open_client`` and ``HTTPClient``
(``hydromodpy/core/io/fetch.py``) and not raw ``requests``, because they handle retry,
backoff, host guards, byte caps and timeouts. A module that holds a source imports
geopandas, pandas, rasterio and requests inside its functions, so a lookup loads
nothing heavy.

The section is usually one flat model. The fields of every source sit side by side and
``source`` selects which are read, so a field name is never reused across two sources of
one variable. ``dem``, ``geology`` and ``crossings`` keep a discriminated union, with
labels that match ``data_sources.names(section)``, ``file`` and ``url`` included.
``value_docs`` renders the explanation of each value on the card of the key.

The sources ``file`` (``FileSource`` in ``hydromodpy/data/source/file.py``) and ``url``
(``UrlSource`` in ``hydromodpy/data/source/url.py``) are registered under each section.
They are the models for a source that asks for neither an extent nor stations.

Register
--------

An in-tree provider is one dotted path in ``_BUILTIN_PATHS`` of
``hydromodpy/data/source/registry.py``, keyed ``<section>_<source_id>``. A plugin
publishes the entry point ``<section>_<source_id>`` in the group
``hydromodpy.data.source``. The mechanism is in :doc:`plug-into-a-port`.

A plugin that fails a check is skipped with a warning that names the fault, so one
broken plugin does not take down a host that asked for another source. A name that the
build already ships under the same section is refused.

A project TOML names the source in its own section.

.. code-block:: toml

   # not checked: acme is the placeholder source of this recipe
   [[data.hydrometry.sources]]
   source = "acme"

In a data request, an installed source resolves by its name alone, with ``options``
handed to the constructor as keyword arguments. A name that two sections share is
refused with both keys.

.. code-block:: json

   {
     "process": {"id": "data-request", "version": "1.0.0"},
     "inputs": {
       "installed": [{"name": "acme", "options": {"max_stations": 5}}],
       "extent": {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"},
       "period": {"start": "2020-01-01", "end": "2020-01-31"}
     }
   }

Test
----

- The config refuses a source name of another section or an unknown name, and a field
  that belongs to another source. ``tests/unit/data/test_variable_families.py`` checks
  that the ``source`` values match what the registry serves and that each has an entry
  in ``schema/sources.py``.
- The provider on a recorded answer, so the tier runs offline.
- A ``SourceCase`` that says which function the source calls, in your clone of this
  repository. ``tests/ports/test_data_source.py`` runs the declarations and the
  refusals on every source the registry serves, an installed one too. The suite is not
  in the wheel, so install your distribution in a clone to run it.

See also
--------

- :doc:`../packages/data` for the variables and the variable template.
- :doc:`add-a-data-variable` for a new variable family.
- :doc:`add-a-config-field` for a new field on an existing source.
- :doc:`add-a-process` for the ``data-request`` capability an orchestrator runs.
