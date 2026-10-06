Add a Process
=============

A *process* in HydroModPy is a runtime payload that one or more
solver adapters consume. Today two processes ship: ``Flow``
(groundwater flow) and ``Transport`` (particle tracking and
concentration). This page describes how to add a third one (for
example ``Heat`` or ``ReactiveTransport``).

Most solver-only additions do **not** need a new process; bind the
new ``solver_name`` to ``"flow"`` or ``"transport"`` instead
(:doc:`add-a-solver`). Add a process only when the runtime payload
is genuinely new (different IC, BC, sink/source vocabulary).

Contract
--------

Every process inherits the abstract base ``ProcessSpatial[TIC]`` from
``hydromodpy/physics/base/process_spatial.py``:

.. code-block:: python

   class ProcessSpatial(ABC, Generic[TIC]):
       parameters: dict[str, FieldParam]
       initial_conditions: TIC | None
       boundary_conditions: dict[str, BoundaryCondition]
       sinks_sources: dict[str, SinkSource]

       @abstractmethod
       def build_initial_conditions(self, ...) -> TIC | None: ...

       @abstractmethod
       def set_boundary_conditions(self, ...): ...

       @abstractmethod
       def set_sinks_sources(self, ...): ...

The matching Pydantic config inherits from ``ProcessSpatialConfig``
declared in
``hydromodpy/physics/base/process_spatial_config.py``.

Files to create
---------------

For a new process called ``heat``:

.. code-block:: text

   hydromodpy/physics/heat/
   |-- __init__.py
   |-- heat.py                       # Heat(ProcessSpatial[HeatInitialConditions])
   |-- heat_config.py                # HeatConfig(ProcessSpatialConfig)
   |-- initial_conditions.py         # HeatInitialConditions
   |-- boundary_conditions.py        # HeatBoundaryConditionConfig
   |-- sinks_sources/
   |   |-- __init__.py
   |   `-- ...
   `-- README.md

The package layout mirrors ``hydromodpy/physics/flow/``. Use that as
the reference template.

Minimal runtime skeleton
------------------------

.. code-block:: python

   # hydromodpy/physics/heat/heat.py
   from dataclasses import dataclass

   from hydromodpy.physics.base.process_spatial import ProcessSpatial


   @dataclass
   class HeatInitialConditions:
       type: str   # "uniform", "from_field", ...
       value: float | None = None


   class Heat(ProcessSpatial[HeatInitialConditions]):
       def build_initial_conditions(self, *args, **kwargs) -> HeatInitialConditions | None:
           ...

       def set_boundary_conditions(self, ...):
           ...

       def set_sinks_sources(self, ...):
           ...

Wire it into ``HydroModPyConfig``
---------------------------------

Add a new TOML section ``[heat]`` backed by ``HeatConfig``:

.. code-block:: python

   # hydromodpy/config/hydromodpy_config.py
   from hydromodpy.physics.heat.heat_config import HeatConfig

   class HydroModPyConfig(BaseModel):
       ...
       heat: HeatConfig | None = None

The Pydantic root validator can refuse the section when no solver
declares ``"heat"`` as ``process_type``, or accept it without solver
binding for prototyping.

Bind one or several solvers
---------------------------

Now register a solver adapter for ``("heat", "<solver_name>")`` (see
:doc:`add-a-solver`). The simulation planner expands every
``[[simulation.process]]`` block of ``type = "heat"`` into one
``ProcessRun`` per declared solver.

Pipeline integration
--------------------

Most processes do **not** need new pipeline steps: ``BuildGeographic``,
``LoadData``, ``BuildMesh``, and ``RunSolver`` are process-agnostic.
The handoff happens through ``ProcessSpatial`` instances stored in
the ``WorkflowContext``.

If your process needs a dedicated forcing chain, add it under
``hydromodpy/physics/forcing/`` and reuse ``ForcingBridge`` /
``time_alignment`` instead of writing a new orchestrator.

Tests to add
------------

- **Unit** under ``tests/unit/physics/heat/`` for the
  ``ProcessSpatial`` contract methods.
- **Integration** under ``tests/integration/physics/`` for one
  end-to-end run with a stub solver.
- **Validation** with at least one analytical reference (heat
  conduction, Dirichlet pulse, etc.) so tolerances are explicit from
  day one.

Pitfalls flagged by the layer matrix
------------------------------------

- ``physics`` may import ``core``, ``schema``, and ``physics``; the
  documented ``physics -> spatial`` tolerance is reserved for
  ``FlowConfig`` field-section discriminated unions and should not
  spread.
- Solver code lives in ``solver/<backend>/``, never inside
  ``physics/``.
- Initial / boundary / sink-source classes stay process-specific;
  the shared base in ``physics/base/`` is intentionally narrow.

See also
--------

- :doc:`../packages/physics` for the physics package map.
- :doc:`add-a-solver` for the matching backend adapter.
- :doc:`add-a-config-field` for adding the new TOML section to the
  Pydantic root.
- :doc:`../layered-architecture` for the layer matrix.
