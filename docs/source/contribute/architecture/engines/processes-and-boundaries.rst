.. _flow-boundary-conditions-runtime-contract:

Processes and boundaries
========================

This note says how a validated configuration becomes the objects a solver reads, and how the
flow boundary conditions travel along that path. The package map of ``hydromodpy.model`` is on
:doc:`../packages/model`, and the boundary table and its binders are in the README of
``hydromodpy/model/boundaries/``. To add a process, read :doc:`../how-to/add-a-process`.

From configuration to solver
----------------------------

.. graphviz::

   digraph handoff {
     rankdir=LR; node [shape=box, fontsize=10];
     cfg   [label="FlowConfig\nTransportConfig"];
     flow  [label="Flow"];
     bind  [label="apply_*_to_flow\n(binders)"];
     model [label="Model\n(frozen)"];
     adapt [label="solver adapter"];
     run   [label="solver run"];
     cfg -> flow [label="set_config"];
     flow -> bind; bind -> flow [style=dashed];
     flow -> model [label="model_from_flow"];
     model -> adapt [label="inputs"];
     adapt -> run;
   }

The configuration classes are Pydantic models under ``HydroModelBase``. ``FlowConfig`` and
``TransportConfig`` share no other base, so a process never carries a key it does not read.
``Flow`` is built from ``FlowConfig`` in ``hydromodpy/model/flow.py``. It holds its parameters,
initial conditions, boundary conditions and sinks and sources. A transport has no runtime
object, because its adapter reads ``TransportConfig`` and the run of its flow.

After the data step, ``workflow/steps/data.py`` calls the ``apply_*_to_flow`` functions of
``hydromodpy/model/boundaries/`` (``climate.py``, ``lakes.py``, ``streams.py`` and
``barriers.py``), and the same cascade runs for a calibration trial. They read no file. They
receive loaded objects and fill the ``Flow``. Recharge and ETP are bound the same way.

``prepare_solver`` then freezes the ``Flow`` into a ``Model`` with ``model_from_flow`` in
``hydromodpy/model/model.py``. A flow adapter reads the ``Model`` and never the ``Flow``, the
configuration or the geographic object. The adapter is the only place that translates runtime
data into solver input formats. A forcing reaches it already resolved to one value per stress
period (``resolve_forcing`` in ``model/forcing/forcing_bridge.py``). The solver side is in
:doc:`backends`, and the walk from the TOML file to the run is in :doc:`toml-to-solver`.

Two classes carry the same idea at two stages. The configuration holds ``FlowInitialCondition``
and ``FlowBoundaryConditionConfig``, which are dedicated flow models. The runtime ``Flow``
stores the generic payloads of ``hydromodpy/model/payloads.py`` (``InitialCondition``,
``BoundaryCondition``, ``SinkSource``). Look at the stage before you edit a class of one of them.

Boundary ids
------------

The public grammar is ``[flow.bc]``. A boundary is active when it is declared, and
``enabled = false`` switches it off. ``active_bc`` is read from the tables in the same way.

Three objects give the runtime contract, all in
``hydromodpy/model/boundaries/boundary_condition_registry.py``.

- ``FlowBoundaryConditionConfig`` (``boundary_conditions.py``) stores one normalized payload.
- ``FLOW_BOUNDARY_DEFINITIONS`` is the table of the known ids, with the family, the default type
  and units, and the support kind. It holds the four sides, ``stream``, ``ocean``, ``drainage``,
  ``lake`` and ``sfr``. The table names no backend.
- ``BoundaryConditionBundle`` groups the configured payloads and the active ids. It reaches the
  adapter as ``Model.boundaries``.

A backend lists the ids it poses in its ``supports``, and ``config/cross_checks.py`` refuses a
file that asks for another one. ``lake`` and ``sfr`` are advanced packages and exist for
MODFLOW 6 only. ``stream`` is not posed by MODFLOW-NWT.

Where each backend assembles a boundary
---------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Backend
     - Module
   * - MODFLOW 6
     - ``hydromodpy/solver/modflow6/builders/boundary_conditions.py`` (``CHD`` and ``DRN``),
       ``lake.py`` and ``sfr.py`` for the advanced packages
   * - MODFLOW-NWT
     - ``hydromodpy/solver/modflow_nwt/nwt/payloads/chd.py`` (``BAS`` and ``CHD``) and
       ``well_drainage.py``
   * - Boussinesq
     - ``hydromodpy/solver/boussinesq/forcing/`` (``dirichlet_support_resolution.py`` and
       ``drainage_resolution.py``)

The tests of the registry are in ``tests/unit/model/boundaries/test_boundary_condition_registry.py``.

Adding a boundary
-----------------

Start with a new row in ``FLOW_BOUNDARY_DEFINITIONS``. The table stays small on purpose. It
describes the canonical ids and does not hide the package semantics of a backend. Then each
backend either implements the id or leaves it out of its ``supports``, so a refusal names it.
How water leaves the aquifer through each id is in :doc:`/theory/exits`.
