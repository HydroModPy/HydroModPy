Add a solver
============

A solver is one class bound to the key ``<process_type>_<name>``, for example
``flow_modflow6`` or ``transport_mt3dms``. The shipped backends are listed in
:doc:`/reference/solvers`. This page adds another flow backend, or a ``transport`` solver.
Both solver ports are experimental (:doc:`../contracts`).

Files to create
---------------

For a new flow backend called ``mysolver``:

.. code-block:: text

   hydromodpy/solver/mysolver/
   |-- __init__.py
   |-- adapter.py          MysolverFlowAdapter, the class of the contract below
   |-- options.py          the Pydantic class of [solver.mysolver], if it has settings
   |-- extractors/flow.py  MysolverOutputAdapter, the extractor
   `-- README.md           the contract of the backend

``hydromodpy/solver/linear_reservoir/`` is the smallest real backend, so read it first.
A MODFLOW-family backend reuses ``hydromodpy/solver/modflow_common/flow_run.py`` for the
build and solve flow. A transport adapter is filed beside its engine, as
``Modflow6GwtTransportAdapter`` is in ``solver/modflow6/transport.py``.
``python -m tools.docs.check_readmes`` counts a backend folder as a port and checks its
README, which follows :doc:`plug-into-a-port`.

Contract
--------

An adapter implements the ``SolverAdapter`` Protocol. The attributes have no default.
The registry refuses a class that leaves one out, or that gives a value outside its
vocabulary, and it names the fault.

.. literalinclude:: /../../hydromodpy/solver/base/adapter_protocol.py
   :pyobject: SolverAdapter

The runner calls ``validate``, then ``build``, then ``run``. ``build`` makes the solver
model in memory and writes nothing. ``run`` writes the input files unless
``solver_run.written`` is set, solves, and returns the run with ``solved`` true.
The extract step calls ``extract``, and the export step calls ``cleanup`` when the run
keeps no solver files. An adapter reads nothing of the setup, the configuration or the
store, and a static gate in ``tests/unit/architecture/`` checks it.

``build`` receives the frozen ``Model``, the options and a ``RunSlot``, and it returns a
``SolverRun``. Both are declared in ``hydromodpy/solver/base/plan.py``.

.. literalinclude:: /../../hydromodpy/solver/base/plan.py
   :pyobject: SolverRun

A flow backend receives no ``upstream`` run. A transport receives exactly one, the flow
named by its ``requires``, and reads ``face_flow`` from it. A flow adapter writes
``face_flow`` and ``connection_cells`` only when ``retention.face_flows`` is true.

Three members are optional, because the registry requires every member of the Protocol body.
``RERUN_MEMBERS`` and ``OPTIONAL_MEMBERS`` in ``adapter_protocol.py`` list them, and the
port test reads both lists.

- ``rerun(previous, model, slot)`` exists if and only if ``mutable`` is not empty. It solves
  a model that differs from ``previous.model`` only by properties named in ``mutable``. It
  returns ``None`` when the change needs a build.
- ``observables`` and ``declared_observables`` serve a calibration trial from the run
  folder, and come together or not at all. A backend refuses what it cannot produce with
  ``ObservableNotAvailableError``.

The extractor is a second class under the same key, typed by ``OutputAdapter`` of the same module.
It declares ``process_type`` and ``solver_name`` (the ``name`` of the adapter) as ``ClassVar[str]``, and
its ``extract(solver_run, store, retention)`` writes the fields and tables of ``writes``.

Minimal skeleton
----------------

.. code-block:: python

   # hydromodpy/solver/mysolver/adapter.py
   from dataclasses import replace
   from typing import ClassVar

   from pydantic import BaseModel

   from hydromodpy.solver.base.plan import RunSlot, SolverRun
   from .options import MysolverOptions


   class MysolverFlowAdapter:
       name: ClassVar[str] = "mysolver"
       process_type: ClassVar[str] = "flow"
       accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular", "triangle"})
       geometry: ClassVar[str] = "cells"
       writes: ClassVar[tuple[str, ...]] = ("head", "budgets")
       reads: ClassVar[tuple[str, ...]] = ()
       supports: ClassVar[frozenset[str]] = frozenset({"recharge", "steady_start"})
       options: ClassVar[type[BaseModel] | None] = MysolverOptions
       category: ClassVar[str] = "distributed"
       native_step: ClassVar[str | None] = None
       mutable: ClassVar[frozenset[str]] = frozenset()
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()

       def validate(self, model, options, slot: RunSlot) -> None: ...

       def build(self, model, options, slot: RunSlot, upstream=()) -> SolverRun:
           return SolverRun(slot=slot, model=model, options=options, solver_model=...)

       def run(self, solver_run: SolverRun) -> SolverRun:
           return replace(solver_run, output_dir=..., written=True, solved=True)

       def extract(self, solver_run: SolverRun, store, retention) -> None: ...

       def cleanup(self, solver_run: SolverRun) -> None: ...

Register
--------

Add one line to each of the two tables ``_BUILTIN_PATHS`` and ``_BUILTIN_EXTRACTOR_PATHS``
of ``hydromodpy/solver/base/registry.py``, under the key ``flow_mysolver``. A backend
outside the tree publishes both entry-point groups ``hydromodpy.solver`` and
``hydromodpy.solver.extractor`` instead. :doc:`plug-into-a-port` explains how both ways
resolve a key. 
What the TOML says
------------------

A file chooses the backend with ``solver.backend = "mysolver"``. The value is checked
against ``solvers.names("flow")`` while the file is read, so a plugin needs no patch to
HydroModPy. The settings are the table ``[solver.mysolver]``. ``SolverConfig`` validates
it with the ``options`` class of the adapter, and a backend whose ``options`` is ``None``
refuses the table. The runner reads it with ``cfg.solver.options_of(name)`` and hands it to
``build``.

A field of the options class takes a ``Profile`` and a ``description``, as in
``solver/linear_reservoir/options.py``. The description is the ``help`` that a check shows
next to the error.

A file that uses a trait the backend leaves out of ``supports`` is refused with
``IncompatibleCapabilitiesError``. The check never names a
backend, so a new backend needs no line in ``config/``. A transport is checked against its
``requires`` the same way. The mesh engines named in ``accepted_meshes`` are checked before
any meshing.

Tests to add
------------

- Unit tests under ``tests/unit/solver/<backend>/`` for ``validate``, ``build``, ``run``
  and ``cleanup``, on a small ``Model`` and a ``RunSlot`` in a temporary folder. A backend
  that carries ``rerun`` adds a test that compares a rerun with a new build, file by file.
- The contract test ``tests/ports/test_solver.py`` runs over ``solvers.names()``, so the
  new backend meets it with no line added.
- ``tests/scenarios/test_backends_write_what_they_declare.py`` plays a small project under
  each in-tree backend and checks that the store holds only names its ``writes`` declares.
- A case under ``tests/validation/`` with an analytical reference, and a
  ``@pytest.mark.solver_sanity`` mark when the backend wraps a binary.

See :doc:`add-a-test` for the full ladder.

The imports the layer matrix allows are in :doc:`../generated/layers`.
:doc:`fix-an-architecture-gate` says what to do when the gate refuses one.

See also
--------

- :doc:`../packages/solver` for the solver package map.
- :doc:`add-a-process` for a new process type.
- :doc:`add-a-config-field` for a field shared by every backend, which belongs to ``[solver]``.
