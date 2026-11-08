Add a config field
==================

Every TOML knob in HydroModPy is backed by a Pydantic v2 model that forbids
extra keys. This page describes how to add a field to an existing section, how
to add a section, and how to write the field so the generated parameter
reference documents it. The reference is built from the models alone, so the
declaration of the field is its documentation.

Find the right model
--------------------

Sections live close to the package they configure:

.. list-table::
   :header-rows: 1
   :widths: 20 24 56

   * - TOML section
     - Pydantic model
     - File
   * - ``[workflow]``
     - ``WorkflowConfig``
     - ``hydromodpy/config/hydromodpy_config.py``
   * - ``[workspace]``
     - ``WorkspaceConfig``
     - ``hydromodpy/core/workspace/config.py``
   * - ``[geographic]``
     - ``GeographicConfig``
     - ``hydromodpy/catchment/preprocess/geographic_config.py``
   * - ``[domain]``
     - ``DomainConfig``
     - ``hydromodpy/model/domain/domain_config.py``
   * - ``[data]``
     - ``DataManagersConfig``
     - ``hydromodpy/data/loading/config_schema.py``
   * - ``[flow]``
     - ``FlowConfig``
     - ``hydromodpy/model/flow_config.py``
   * - ``[transport]``
     - ``TransportConfig``
     - ``hydromodpy/model/transport/transport_config.py``
   * - ``[simulation]``
     - ``SimulationConfig``
     - ``hydromodpy/solver/base/simulation_config.py``
   * - ``[solver]``
     - ``SolverConfig``, and the settings table of each flow solver under it
       (``[solver.modflow6]``, ``[solver.modflow_nwt]``, ``[solver.boussinesq]``)
     - ``hydromodpy/solver/base/solver_config.py``
   * - ``[display]``
     - ``DisplayConfig``
     - ``hydromodpy/display/config.py``
   * - ``[site]``
     - ``SiteConfig``
     - ``hydromodpy/core/site/config.py``
   * - ``[sites]``
     - ``SitesConfig``
     - ``hydromodpy/config/sites.py``
   * - ``[metrics]``
     - ``MetricsConfig``
     - ``hydromodpy/results/metric_rule.py``
   * - ``[publication]``
     - ``PublicationConfig``
     - ``hydromodpy/results/publication.py``
   * - ``[overview]``
     - ``OverviewConfig``
     - ``hydromodpy/display/overview/config.py``
   * - ``[mesh]``
     - ``MeshConfig``
     - ``hydromodpy/mesh/mesh_config.py``
   * - ``[calibration]``
     - ``CalibrationConfig``
     - ``hydromodpy/calibration/config.py``

A named table
-------------

The settings of a flow solver are not a section of the root. A key of ``[solver]`` that is not one
of its own fields is the name of a flow solver, and its table is validated by the ``options`` class
that the adapter declares (``hydromodpy/solver/modflow6/modflow6_config.py``,
``hydromodpy/solver/modflow_nwt/nwt/nwt_config.py``, ``hydromodpy/model/runtime_config.py``).
To add a field to such a table, add it on that class with the same rules as any other field.
``SolverConfig.named_tables(shipped_only=True)`` hands the classes of the shipped solvers to the
schema, the template, the parameter pages and the dotted paths, so none of them needs a line for a
new field. A field that every flow solver reads belongs to ``[solver]`` itself. If a solver ignores
it, the solver leaves it out of ``supports`` and a file that sets it is refused when it is read.

Pydantic invariants
-------------------

Every model in HydroModPy must:

- inherit from ``HydroModelBase`` (or a model that does), which forbids extra
  keys and validates on assignment;
- use a unit type for unit-bearing fields (see below);
- carry a ``Profile`` annotation on every field;
- ship a ``Field(..., description="...")``.

Pick a unit type
----------------

Quantitative fields use the unit aliases declared in
``hydromodpy/core/units/types.py``:

.. list-table::
   :header-rows: 1
   :widths: 28 24 48

   * - Alias
     - Canonical unit
     - Use for
   * - ``Length``
     - m
     - Lengths, distances, depths
   * - ``Area``
     - m²
     - Surfaces
   * - ``Volume``
     - m³
     - Volumes
   * - ``Time``
     - s
     - Durations
   * - ``FlowRate``
     - m³/s
     - Discharges
   * - ``Velocity``
     - m/s
     - Fluxes, recharge rates
   * - ``HydraulicConductivity``
     - m/s
     - K
   * - ``SpecificStorage``
     - 1/m
     - Ss
   * - ``SpecificYield``
     - dimensionless
     - Sy
   * - ``Dimensionless``
     - dimensionless
     - Pure ratios

Bare numbers are interpreted in the canonical SI unit; users can also
pass strings such as ``"50 m"`` or ``"0.36 m/h"`` and Pydantic will
auto-convert.

Pick a profile
--------------

``hydromodpy/core/config_kit/profile.py`` declares three visibility
levels:

.. code-block:: python

   class Profile(IntEnum):
       USER = 1     # hydrogeologist: physics, paths, project I/O
       DEV = 2      # developer: tolerances, backends, cache
       EXPERT = 3   # MODFLOW / Boussinesq / pint internals

Default to ``Profile.USER``. Demote to ``DEV`` or ``EXPERT`` only
when the field is genuinely irrelevant for non-developer users.

Template generation, JSON Schema export, and frontend forms all
respect the chosen Profile.

Add a field to an existing section
----------------------------------

.. code-block:: python

   # hydromodpy/model/flow_config.py
   from typing import Annotated
   from pydantic import Field
   from hydromodpy.core.config_kit.profile import Profile
   from hydromodpy.core.units import HydraulicConductivity


   class FlowConfig(HydroModelBase):
       # ... existing fields ...

       k_aquifer: Annotated[HydraulicConductivity, Profile.USER] = Field(
           default=1e-5,
           description="Aquifer hydraulic conductivity (canonical: m/s).",
           examples=[1e-4, "0.36 m/h"],
       )

In TOML, a bare number is read in the canonical unit and a string carries its
own:

.. code-block:: toml

   # not checked: k_aquifer is the example of this page, not a key of the model
   [flow]
   k_aquifer = 1e-4         # interpreted as m/s

.. code-block:: toml

   # not checked: k_aquifer is the example of this page, not a key of the model
   [flow]
   k_aquifer = "0.36 m/h"   # converted to m/s

Tracked input files
-------------------

If the field carries a path, annotate it with ``InputFile`` from
``hydromodpy/core/tracking/input_file.py``:

.. code-block:: python

   from hydromodpy.core.tracking.input_file import InputFile

   dem_path: Annotated[Path, InputFile(role="dem", category="data", portable=True)] = ...

The reproducibility manifest will list the file, its canonical path,
and its SHA-256 automatically.

Cross-field validators
----------------------

Use ``@field_validator(mode="before")`` for normalization
(parse-then-validate) and ``@model_validator(mode="after")`` for
cross-field invariants. Keep them small and explicit.

Add a brand-new section
-----------------------

1. Create the Pydantic model in the appropriate package.
2. Add the field to ``HydroModPyConfig`` in
   ``hydromodpy/config/hydromodpy_config.py``, with a default factory or
   ``None``, and its entry in the section loader table of the same file.
3. If a launcher should dispatch on the new section, wire it through
   ``hydromodpy/project/dispatch/workflow.py`` (or the equivalent dispatcher).
4. Regenerate the committed JSON Schema with
   ``python -m tools.docs.schema_export`` and commit the diff.
   ``tests/unit/docs/test_docs_config_consistency.py`` fails while the file in
   ``docs/source/_static/`` differs from what the code exports. The frontend
   export, ``hmp config schema --bundle --to DIR``, is written on demand and is not committed.

Describe the field
------------------

The parameter reference is generated from the models, so nothing is written on
a page. Change the field, and the next build shows the change everywhere the
key appears. This is what the reference reads from a declaration:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - The reader sees
     - It comes from
   * - The path of the key and its place in the file
     - The model tree under ``HydroModPyConfig``.
   * - The one-line summary
     - The first sentence of ``description``.
   * - The text of the card
     - The whole ``description``.
   * - The form of the value: number, text, list, table
     - The annotation.
   * - The unit
     - A quantity type (``Length``, ``HydraulicConductivity``, ...), else
       ``field_metadata(unit=...)``, else ``Calibrable(units=...)``, else a
       suffix of the field name such as ``_m`` or ``_days``.
   * - The default, or *required*
     - ``default``, ``default_factory``, or no default.
   * - The range
     - ``ge``, ``gt``, ``le``, ``lt``.
   * - The allowed values
     - ``Literal[...]``.
   * - What each value does
     - ``field_metadata(value_docs={...})``.
   * - The value written on a required line
     - The first item of ``Field(examples=[...])``.
   * - Shown by default, or behind the developer and expert button
     - ``Profile.USER``, ``Profile.DEV``, ``Profile.EXPERT`` in the annotation.
   * - When the key is read
     - ``VisibleWhen("sibling", value)`` in the annotation.
   * - The *calibrable* badge and its search space
     - ``field_metadata(calibrable=Calibrable(...))``.
   * - The *experimental* and *deprecated* badges
     - ``field_metadata(stability="experimental")`` and ``Field(deprecated=...)``.
   * - "Connections found in the code"
     - Other sections named in the same function or string of ``hydromodpy/``.

``field_metadata`` lives in ``hydromodpy/core/config_kit/field_metadata.py``. It
refuses an unknown key when the module is imported, so a typo fails the tests
and not the page.

The first sentence of the description is the summary: it shows on the line of
the key, in the tree of the whole file and in the search. Make it say what the
key sets, in the words of the person who writes the file. The conditions where
the key applies and its exceptions come after it.

.. code-block:: python

   geology: Annotated[Literal["face", "none"], StripLower, Profile.USER] = Field(
       default="face",
       description=(
           "How the mesh follows the contacts between the zones of the vector geology "
           "map that a flow parameter reads."
       ),
       json_schema_extra=field_metadata(
           value_docs={
               "face": "Cell faces lie on the contacts between geology zones.",
               "none": "The mesh ignores the geology contacts.",
           }
       ),
   )

Rules for the values:

- A choice between values is a ``Literal``, and every value is explained in
  ``value_docs``. The card lists the values with their explanation, and the
  search finds a key by the name of one of its values.
- A number has a unit. A quantity type also lets the file write ``"150 m"`` or
  ``"3 days"``, and a bare number is read in the canonical unit.
- A key read only in some cases says so with ``VisibleWhen``, not only in the
  prose: the card then shows the condition on its own line.
- A required key with no default has an example in ``Field(examples=[...])``. It
  is the value the reference writes on the line of the key. Never take it from
  an example project.

Build the documentation and open the page of the section to check it
(``make -C docs html-strict``). The build fails on a cited key that does not
exist. The tree of the whole file, :doc:`/reference/parameters/explorer`, is the
fastest way to see the key in context.

Tests to add
------------

- **Unit** under ``tests/unit/config/`` for accept / reject cases
  (extra fields rejected, units parsed, validators raised on bad
  combos).
- **Integration** if the field changes the dispatched workflow.

Run ``hmp config check <toml>`` to validate any candidate TOML
against the new model.

Rename, move or remove a key
----------------------------

A stable key leaves under the rules of :doc:`/about/versions`, so it keeps loading
for two minor versions. In one change:

1. Add a row to ``RENAMED_KEYS`` in ``hydromodpy/config/config_migration.py``, with
   ``since`` set to the version that will ship the change, or a row to ``MOVED_TABLES``
   when the key or the table changes place. A load then reads the old name with a
   warning, and ``hmp doctor --fix-config`` rewrites the file and the files it inherits.
   That one row also carries the dotted paths that name the key: the ``overrides`` of a
   calibration phase, ``path`` and ``target`` of a calibration parameter, the keys of
   ``[sites.bind]`` and of the ``set`` table of a recipe, ``--set``, ``HMP_SET_*``, and
   the directives ``<old>__append``, ``<old>__merge`` and ``<old>__delete``. A figure
   option is a row with the scope ``display.overrides.{*}``.
2. List the old key in the ``model_refused_keys`` of the model, with ``renamed_to``, so
   a config built in Python is told what to write. A plain rename of ``[calibration]`` is
   one row of ``CALIBRATION_RENAMES`` in ``hydromodpy/calibration/config.py`` instead, which
   fills both tables. Any row under ``[calibration]`` has no delay, because the section is
   experimental: a load refuses the file with the new name, the doctor rewrites it, and a
   sealed run still reads it.
3. Name the old path in ``renamed_from`` on the new field, so the changes page lists
   the rename.
4. Run ``python -m tools.surface_snapshot``. It refuses a stable key that has no row in
   the table, and it records the key in ``removed_toml_keys.tsv``.
5. Write the old and the new name under ``Changed`` in the changelog.

``tests/unit/config/test_historical_configs.py`` loads real files of the published alphas
from ``tests/unit/config/corpus/``, so a rename with no row fails there.

A row outlives its delay when the version of the package reaches ``since`` plus two
minor versions, and ``tests/unit/config/test_config_migration.py`` then fails. Set
``sealed_only=True`` on the row at that point: a live file is refused, and a run sealed
under the old name stays readable.

Pitfalls flagged by the layer matrix
------------------------------------

- The Pydantic model lives in the **same** layer as the package it
  configures. Do not move it to ``config/``: ``config/`` is the root
  composition only.
- ``config/`` is the one layer that composes the sections, so it imports the
  layers that own them. Of the layers below it, only ``schema/`` and ``results/``
  import ``config/``.
- The committed JSON Schema must stay in sync with the models. Re-run the
  export after every field addition.

See also
--------

- :doc:`../packages/config` for the configuration root.
- :doc:`../packages/core` for ``Profile``, units, and tracking
  helpers.
- :doc:`build-a-frontend` if your field powers a UI widget.
- :doc:`/contribute/documentation/index` for the rest of the documentation.
- :doc:`/reference/parameters/index` for the user-facing TOML
  reference (auto-generated from these models).
