Process Runtime To Solver Sequence
==================================

Scope
-----

This diagram shows the main runtime handoff from process objects to solver
backends.

It focuses on:

- runtime construction of ``Flow`` from validated config,
- recharge chronicle preparation before solver assembly,
- adapter-level transformation into solver payloads,
- backend-specific execution path (MODFLOW-NWT or MODFLOW 6).

Code map
--------

- ``hydromodpy/process/flow/flow.py``:
  runtime object assembled before solver dispatch.
- ``hydromodpy/process/flow/time_forcing.py``:
  forcing preparation before solver assembly.
- ``hydromodpy/solver/<backend>/adapters/``:
  adapter layer that translates process objects into backend payloads.
- ``hydromodpy/solver/modflow_common/`` and backend packages:
  concrete solver consumers.

Recommended reading path
------------------------

1. ``hydromodpy/process/flow/flow.py``
2. ``hydromodpy/process/flow/time_forcing.py``
3. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py``
4. one backend adapter such as ``modflow6.py`` or ``modflownwt.py``
5. the matching solver package under ``hydromodpy/solver/``

Diagram source
--------------

.. uml:: diagrams/runtime_to_solver_sequence.wsd

.. literalinclude:: diagrams/runtime_to_solver_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process runtime to solver sequence

Notes
-----

- The sequence is logical and backend-agnostic at the high level.
- Payload conversion is explicitly separated from process runtime state.
- Recharge forcing is prepared before solver assembly and injected as
  already-aligned series.
- Solver wrappers remain consumers of already-normalized process data.
- For detailed DIS payload semantics, see
  ``docs/developers/modflow_discretization_contract.md``.

Related diagrams
----------------

- :doc:`process-runtime-class-diagram`
- :doc:`../simulation/launcher-simulation-class-diagram`
- :doc:`../solver/index`
