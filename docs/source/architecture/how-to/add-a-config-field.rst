Add a Config Field
==================

Every TOML knob in HydroModPy is backed by a Pydantic v2 model with
``ConfigDict(extra="forbid")``. This page describes how to add a new
field to an existing section, or how to add a brand-new section.

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
     - ``hydromodpy/data/managers/config_schema.py``
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
   * - ``[persistence]``
     - ``PersistenceConfig``
     - ``hydromodpy/core/config_kit/persistence.py``
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

- inherit from ``HydroModelBase`` (or a model that does);
- declare ``model_config = ConfigDict(extra="forbid")``;
- use ``Annotated`` for unit-bearing fields (see below);
- carry a ``Profile`` annotation on every field;
- ship a ``Field(..., description="...")`` and at least one example
  for documented fields.

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

Pick a Profile
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

In TOML, both forms work:

.. code-block:: toml

   [flow]
   k_aquifer = 1e-4         # interpreted as m/s
   # or
   k_aquifer = "0.36 m/h"   # auto-converted to m/s

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
   ``hydromodpy/config/hydromodpy_config.py`` (typically as
   ``Annotated[NewConfig | None, Profile.USER] = None``).
3. If a launcher should dispatch on the new section, wire it through
   ``hydromodpy/project/dispatch/workflow.py`` (or the equivalent dispatcher).
4. Refresh the JSON Schema export with
   ``hmp schema export --output ./schema/`` and commit the diff if
   the project pins generated artefacts.

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
- ``schema/`` and ``config/`` may both import any other layer; new
  cross-edges should still be justified.
- Generated TOML templates and JSON Schema exports must stay in sync
  with the source models. Re-run the export after every field
  addition.

See also
--------

- :doc:`../packages/config` for the configuration root.
- :doc:`../packages/core` for ``Profile``, units, and tracking
  helpers.
- :doc:`build-a-frontend` if your field powers a UI widget.
- :doc:`/user_guide/config_reference/index` for the user-facing TOML
  reference (auto-generated from these models).
