Add a Data Variable
===================

A *data variable* is a thematic family loaded by ``Project.load_data``
and stored in the input cache. Today seventeen variables ship under
``hydromodpy/data/variables/``: ``hydrometry``, ``piezometry``,
``water_quality``, ``hydrography``, ``oceanic``, ``geology``,
``dem``, ``precipitation``, ``temperature``, ``etp``,
``soil_moisture``, ``humidity``, ``recharge``, ``runoff``,
``radiation``, ``wind``, ``intermittency``.

Add a brand-new variable only when the family is genuinely new (a
new physical quantity with its own normalisation contract). To add a
**source** to an existing variable, see :doc:`add-a-data-source`
instead.

Two manager flavours
--------------------

- **Point variables** (gauges, observations) inherit from
  ``BaseVariableManager`` and emit ``PointRecord`` objects.
- **Field variables** (rasters, gridded forcing) inherit from
  ``BaseFieldManager`` and emit ``FieldRecord`` objects.

Both contracts live under ``hydromodpy/data/`` (``base_manager_variable.py``,
``base_manager_field.py``, ``_base_manager_common.py``).

Files to create
---------------

For a new variable called ``newvar``:

.. code-block:: text

   hydromodpy/data/variables/newvar/
   |-- __init__.py                   # exports
   |-- config.py                     # NewvarSourceConfig, NewvarConfig
   |-- manager.py                    # NewvarManager(BaseVariableManager|BaseFieldManager)
   |-- custom.py                     # load_custom(source_cfg, project_period)
   |-- contracts.py                  # variable-specific record fields if any
   |-- apis/
   |   |-- __init__.py
   |   `-- <source_name>.py          # one file per public source
   `-- README.md                     # short rationale

Use ``hydromodpy/data/variables/hydrometry/`` as the canonical
template for point variables, ``hydromodpy/data/variables/dem/`` for
field variables.

Manager skeleton
----------------

.. code-block:: python

   # hydromodpy/data/variables/newvar/manager.py
   from typing import ClassVar

   from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
   from hydromodpy.data.contracts.timeseries import PointRecord
   from hydromodpy.data.contracts.load_result import LoadResult


   class NewvarManager(BaseVariableManager):
       VARIABLE_NAME: ClassVar[str] = "newvar"

       def _fetch_from_source(self, source_cfg, project_period):
           # dispatch on source_cfg.source ("custom", "myapi", ...)
           # return LoadResult(points=[PointRecord(...)], fields=[], warnings=[])
           ...

The base class handles cache lookups, persistence to CSV plus LOC
metadata, registration in the catalog, and warning aggregation.

Config block
------------

Each variable owns one block under ``[data.<variable>]`` with a
``sources`` list:

.. code-block:: toml

   [data.newvar]
   date_start = "2020-01-01"
   date_end = "2020-12-31"

   [[data.newvar.sources]]
   source = "myapi"
   product = "qmnj"
   extent = "watershed"

The matching Pydantic models:

.. code-block:: python

   # hydromodpy/data/variables/newvar/config.py
   from typing import Annotated, Literal
   from pydantic import BaseModel, ConfigDict, Field

   from hydromodpy.core.config_kit.profile import Profile


   class NewvarApiSourceConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")
       source: Literal["myapi"]
       product: Annotated[str, Profile.USER]
       extent: Annotated[str, Profile.USER] = "watershed"


   class NewvarCustomSourceConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")
       source: Literal["custom"]
       path: Annotated[str, Profile.USER]


   NewvarSourceConfig = NewvarApiSourceConfig | NewvarCustomSourceConfig


   class NewvarConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")
       date_start: Annotated[str | None, Profile.USER] = None
       date_end: Annotated[str | None, Profile.USER] = None
       sources: list[NewvarSourceConfig] = Field(default_factory=list)

Source modules
--------------

There is no source registry. Each public API source is a plain module
exposing a ``fetch`` function:

.. code-block:: python

   # hydromodpy/data/variables/newvar/apis/myapi.py
   from hydromodpy.data.contracts.timeseries import PointRecord


   def fetch(station_ids, start, end) -> list[PointRecord]:
       ...

``NewvarManager._fetch_from_source`` dispatches on
``source_cfg.source`` and imports the module lazily inside the matching
branch. See :doc:`add-a-data-source` for the full wiring.

Wire it into the planner
------------------------

``DataPlanner`` (``hydromodpy/data/managers/planner.py``) merges the
``[data].types`` list with rules that infer extra families from other
sections (geology if the domain references "geology", hydrography if
the flow uses ``"stream"`` boundary conditions, etc.). If your
variable should be auto-inferred from a foreign config, add the rule
to the planner.

Otherwise the user activates it explicitly:

.. code-block:: toml

   [data]
   types = ["newvar"]

Wire it into ``HydroModPyConfig``
---------------------------------

In ``hydromodpy/data/managers/config_schema.py`` (or the equivalent
discriminated union), add ``NewvarConfig`` so ``[data.newvar]``
parses cleanly.

Tests to add
------------

- **Unit** under ``tests/unit/data/newvar/`` for the config parsers,
  the custom loader on a fixture file, and the manager's normalisation
  contract.
- **Integration** under ``tests/integration/data/`` for one
  ``Project.load_data`` cycle using a stub source.
- **Replay** under ``hydromodpy/data/examples/`` (or a dedicated
  fixtures folder) for any HTTP-backed source so smoke tests can run
  offline.

Run ``hmp data list`` after a manual cache write to confirm the
catalog row appears.

Pitfalls flagged by the layer matrix
------------------------------------

- ``data`` may import ``core`` and ``schema`` only. The
  ``data -> spatial`` tolerance is strictly reserved for the geology
  field bridge.
- Do not import ``simulation``, ``solver``, ``calibration``,
  ``results``, ``display``, ``analysis`` from a manager.
- The data layer must not depend on a workspace; the optional
  ``workspace.cache`` lives separately and is set at runtime.
- Records emitted by the manager must be timezone-aware when they
  carry datetimes (UTC by default).

See also
--------

- :doc:`../packages/data` for the data package map and the existing
  variables.
- :doc:`add-a-data-source` for adding a new source to an existing
  variable.
- :doc:`add-a-config-field` if the new variable needs a dedicated
  TOML knob outside the source list.
- :doc:`/user_guide/data/index` for the user-facing data loading
  guide.
