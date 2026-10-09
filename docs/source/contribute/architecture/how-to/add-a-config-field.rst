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
     - ``hydromodpy/spatial/geographic/geographic_config.py``
   * - ``[domain]``
     - ``DomainConfig``
     - ``hydromodpy/spatial/domain/domain_config.py``
   * - ``[data]``
     - ``DataManagersConfig``
     - ``hydromodpy/data/loading/config_schema.py``
   * - ``[flow]``
     - ``FlowConfig``
     - ``hydromodpy/physics/flow/flow_config.py``
   * - ``[transport]``
     - ``TransportConfig``
     - ``hydromodpy/physics/transport/transport_config.py``
   * - ``[simulation]``
     - ``SimulationConfig``
     - ``hydromodpy/simulation/planning/config.py``
   * - ``[solver]``
     - ``SolverConfig``
     - ``hydromodpy/solver/base/solver_config.py``
   * - ``[modflownwt]``
     - ``ModflowConfig``
     - ``hydromodpy/solver/modflow_nwt/nwt/nwt_config.py``
   * - ``[modflow6]``
     - ``Modflow6Config``
     - ``hydromodpy/solver/modflow6/modflow6_config.py``
   * - ``[display]``
     - ``DisplayConfig``
     - ``hydromodpy/display/config.py``
   * - ``[analysis]``
     - ``AnalysisConfig``
     - ``hydromodpy/analysis/config.py``
   * - ``[overview]``
     - ``OverviewConfig``
     - ``hydromodpy/display/overview/config.py``
   * - ``[mesh_catchment]``
     - ``MeshCatchmentConfig``
     - ``hydromodpy/spatial/mesh/config/``
   * - ``[calibration]``
     - ``CalibrationConfig``
     - ``hydromodpy/calibration/config.py``

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

   # hydromodpy/physics/flow/flow_config.py
   from typing import Annotated
   from pydantic import Field
   from hydromodpy.core.config_kit.profile import Profile
   from hydromodpy.core.units import HydraulicConductivity


   class FlowConfig(ProcessSpatialConfig):
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

Use ``@field_validator(mode="before")`` for normalisation
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
   export, ``hmp dev schema export``, is written on demand and is not committed.

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
   * - The *calibrable* badge and its transform
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

   grid_dual: Annotated[Literal["voronoi", "triangle"], Profile.USER] = Field(
       default="voronoi",
       description=(
           "Cell shape of a runtime gmsh mesh: the Voronoi (PEBI) dual or the "
           "triangles themselves. Applies only to a MODFLOW 6 run on a runtime "
           "gmsh mesh; ignored for structured grids."
       ),
       json_schema_extra=field_metadata(
           value_docs={
               "voronoi": "Exact CVFD orthogonality, about half the cells. The default.",
               "triangle": "Keeps the triangulation cells, for simplex comparison runs.",
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

Pitfalls flagged by the layer matrix
------------------------------------

- The Pydantic model lives in the **same** layer as the package it
  configures. Do not move it to ``config/``: ``config/`` is the root
  composition only.
- ``config/`` is the one layer that composes the sections, so it imports the
  layers that own them. Of the layers below it, only ``schema/``, ``results/``
  and ``reporting/`` import ``config/``.
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
