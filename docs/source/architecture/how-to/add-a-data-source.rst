Add a Data Source
=================

A *source* is one value a user may write in ``source =`` for an existing
variable: a public API, the user's own files (``custom``), or a generator
(``constant``, ``synthetic``). For a brand-new variable family, see
:doc:`add-a-data-variable` first.

Two paths, and which one you are on
-----------------------------------

**In this repository**, a provider is a function in the variable's package
and one entry in its manager's ``SOURCES`` table. That is how every shipped
variable reaches Hub'Eau, SIM2, the BRGM, the IGN or the SHOM.

**Out of tree**, a provider is a ``DataSource`` class (the port,
``hydromodpy/data/source/port.py``) published on the
``hydromodpy.data.source`` entry-point group. It is nameable in a
``[data.hydrography]`` section when it serves a river network, and for any
payload kind under the ``installed`` member of a data request, without a
patch to this repository.

An in-tree provider
-------------------

Three edits, all inside the variable's package, plus one line of the source
table:

1. the provider module, ``variables/<variable>/apis/<provider>.py`` (or
   ``common/clients/`` when several variables share it, as SIM2 does);
2. the value in the ``source`` field of ``variables/<variable>/config.py``;
3. the entry in the manager's ``SOURCES`` table;
4. an entry (licence, network hosts) in ``hydromodpy/schema/sources.py``.

A station provider has the form
``fetch(cfg, *, bbox, station_ids, start, end, context)``, a gridded one
``fetch(cfg, *, bbox, period, context)``. ``cfg`` is the validated source
section, ``bbox`` the box the manager resolved for the provider's CRS, and
``context`` a ``SourceContext``: project extent, cache folder, section dates,
nearest point.

.. code-block:: python

   # hydromodpy/data/variables/wind/apis/acme.py
   from hydromodpy.data.contracts.spatial_field import FieldRecord


   def fetch(cfg, *, bbox, period, context) -> list[FieldRecord]:
       """Wind speed from the Acme grid service, over bbox and period."""
       ...

.. code-block:: python

   # hydromodpy/data/variables/wind/config.py
   source: Annotated[Literal["custom", "sim2", "acme"], Profile.USER] = Field(
       ...,
       description="Data provider.",
       json_schema_extra={"value_docs": {"acme": "Wind speed from the Acme service."}},
   )

.. code-block:: python

   # hydromodpy/data/variables/wind/manager.py
   from hydromodpy.data.variables.wind.apis import acme


   class WindManager(BaseFieldManager):
       VARIABLE_NAME = "wind"
       INTERNAL_UNIT = "m/s"
       SOURCES = {"sim2": sim2_source("wind"), "acme": acme.fetch}

The manager owns the cache: ``BaseFieldManager`` keeps grids as NetCDF,
``BaseVariableManager`` keeps chronicles per station and asks the provider
only for the missing periods. A provider never opens the catalogue.

A grid provider is cached only when it can say which variables it returns:
give the function a ``variables(cfg)`` attribute, as ``sim2_source`` does.
Without it the provider is called on every load and receives
``bbox=None``, which is right for a local generator and wrong for a download.

Use ``get_json`` (``hydromodpy/data/common/api_client.py``) or ``HTTPClient``
(``hydromodpy/core/io/http_client.py``) rather than raw ``requests``: they
handle retry, backoff and timeout.

``tests/unit/data/test_the_variable_families_agree.py`` checks that the
``source`` values of each variable (``custom`` aside) are exactly the keys of
its ``SOURCES``, and that each has an entry in ``schema/sources.py``; a
missing edit fails there with the file to complete. ``value_docs`` renders
the per-value table of the configuration reference, which
``python -m tools.doc_config`` regenerates.

The source section is **one flat model**: every source's fields sit side by
side and ``source`` selects which are read. ``extra="forbid"`` refuses an
unknown key, not a field of another source of the same section, so a field
name is never reused across two sources of one variable.

Custom files and generators
---------------------------

``source = "custom"`` never appears in ``SOURCES``: the base class loads the
user's files with ``load_custom``, from the manager's ``VARIABLE_NAME`` and
``INTERNAL_UNIT``. A variable whose files need real work overrides it, or
keeps a ``custom.py`` beside its manager. A generator is a module named after
its value (``recharge/synthetic.py``, ``oceanic/constant.py``) with the same
signature as a provider.

A plugin source
---------------

Eight members, seven of them class-level declarations read *before* any fetch
runs, and one ``fetch``:

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
       require_period,
       require_selectors,
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
           require_selectors(self, request)
           period = require_period(self, request)
           extent = extent_for(self, request)  # converted into extent_crs
           ...

``variables`` belongs to the instance, because a source configured one way
may serve fewer variables than the class can. Everything else is a
``ClassVar``, so the registry refuses a non-conforming class when it is
registered, not mid-fetch.

A source must **not** know the DuckDB catalogue, the project workspace, a
lock or a cache. It receives an ``Extent`` carrying its own CRS, an optional
``Period`` and an ``out_dir`` scratch it owns alone.

Publish it from your own distribution:

.. code-block:: toml

   # your package's pyproject.toml
   [project.entry-points."hydromodpy.data.source"]
   acme-radar = "mypackage.acme_radar:AcmeRadarSource"

The entry-point name must equal the ``source_id`` the class declares: a
request writes the name and a result is stamped with the ``source_id``. A
name this build already ships is refused. A plugin that fails any check is
skipped with a warning naming what is wrong, never raised: one broken plugin
must not take down a host that asked for a different source.

Name it from a document
-----------------------

.. code-block:: toml

   # a project TOML. The section names a source whose payload kind is
   # "features"; a source of another kind is refused by the document.
   [[data.hydrography.sources]]
   source = "acme-linework"

.. code-block:: json

   {
     "process": {"id": "data-request", "version": "1.0.0"},
     "inputs": {
       "installed": [{"name": "acme-radar", "options": {"sweep": "short"}}],
       "extent": {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"},
       "period": {"start": "2020-01-01", "end": "2020-01-31"}
     }
   }

``options`` is handed to the constructor as keyword arguments and bound
against its signature before anything runs, so an argument the source cannot
take is refused by name. An installed source does not appear in the process
description, which ships frozen in the wheel, and the hosts it reaches are
not in ``hmp:invocation.network``; ``outputs/request.json`` names the source
of each file the run wrote.

A ``[[data.hydrography.sources]]`` section is flat and shared by every source
it can name, so the binder hands a plugin **the section field its constructor
names, and nothing else**. A name the section does not carry keeps your
default; a positional-only parameter without a default is refused.

``tests/contract/test_data_source_contract.py`` holds every shipped source to
the port: the payload kind it claims, the CRS the provider is really asked
in, whether a period is really required, whether ``out_dir`` is left alone.

Tests to add
------------

- the config: a value the section refuses, a field that belongs to another
  source;
- the provider on a recorded answer, so the tier runs offline;
- for a plugin, the contract suite parametrised on your class, in your own
  distribution.

See also
--------

- :doc:`../packages/data` for the variable inventory and the manager template.
- :doc:`add-a-data-variable` for a new variable family.
- :doc:`add-a-config-field` for a new field on an existing source.
- :doc:`/user_guide/data/index` for the user-facing provider matrix.
- :doc:`add-a-process` for exposing work as a capability an orchestrator runs,
  which is what ``data-request`` is.
