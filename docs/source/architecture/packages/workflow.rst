workflow
========

``hydromodpy.workflow`` provides composable steps and an immutable
``PipelineState`` payload that flows from one step to the next. The
``Project`` facade and every workflow launcher (simulation,
calibration, batch, comparison, testbed) reuse these steps so the
same TOML always drives the same lifecycle.

Sub-modules
-----------

- ``workflow/internals/state.py`` -- ``PipelineState[TPayload]``
  generic dataclass, immutable, specialised by step
  (``ValidatedState``, ``ResolvedState``, ``GeographicState``,
  ``LoadedState``, ``MeshedState``, ``SetupState``,
  ``OpenStoreState``, ``SolverRanState``, ``ExtractedState``,
  ``DerivedState``, ``ExportedState``). Transit through
  ``state.advance(...)``.
- ``workflow/internals/step.py`` -- ``Step[TIn, TOut]`` Protocol
  (``name``, ``run(state) -> state``, optional ``config_sections``).
- ``workflow/internals/checkpoint.py`` -- ``CheckpointStore`` with
  HMAC-SHA256 signed pickle plus zstd compression.
- ``workflow/internals/ledger.py`` -- DuckDB ledger of executed
  steps.
- ``workflow/internals/dependencies.py`` --
  ``earliest_affected_step`` resolves the first pipeline index
  affected by a dotted-path override (used by calibration to skip
  shared phases).
- ``workflow/internals/derived.py`` -- ``DerivedRegistry`` for
  ordered post-extraction calculations.
- ``workflow/internals/manifest.py`` -- ``WorkflowManifest`` summary
  for the lockfile.
- ``workflow/runner.py`` -- ``Pipeline`` runner that chains steps,
  manages the ledger, the optional checkpoint store, and typed
  errors (``StepError`` exposes ``step_name`` and ``run_id``).
- ``workflow/steps/`` -- the canonical step library.
- ``workflow/pipelines/`` -- pre-assembled pipelines for the
  standard workflows.

Twelve canonical steps
----------------------

Defined under ``workflow/steps/`` and re-exported from
``workflow/steps/__init__.py``:

``ValidateStep``, ``ResolveStep``, ``LoadDataStep``,
``BuildGeographicStep``, ``BuildMeshStep``,
``SetupProcessStep``, ``PrepareSolverStep``, ``RunSolverStep``,
``ExtractStep``, ``DeriveStep``, ``DisplayStep``, ``ExportStep``.

``DisplayStep`` runs before ``ExportStep``: figures are the last reader
of a run, so they draw from the open store while the intermediate fields
are still there. ``ExportStep`` then drops what reconciliation forced on
(the per-cell budget) and seals the store.

Step contract
-------------

.. code-block:: python

   class XyzStep:
       name: ClassVar[str] = "xyz"
       tin: ClassVar[type] = InputPayloadType
       tout: ClassVar[type] = OutputPayloadType
       config_sections: ClassVar[tuple[str, ...]] = ("flow.param",)

       def run(self, state: PipelineState) -> PipelineState:
           ...
           return state.advance(
               step_index=...,
               step_name=self.name,
               payload=...,
           )

The ``config_sections`` annotation declares which TOML subtrees the
step reads. ``earliest_affected_step`` walks every step's
declarations to decide which phases can be skipped per calibration
trial.

Key public symbols
------------------

- ``hydromodpy.workflow.internals.state.PipelineState``
- ``hydromodpy.workflow.internals.step.Step``
- ``hydromodpy.workflow.internals.checkpoint.CheckpointStore``
- ``hydromodpy.workflow.internals.dependencies.earliest_affected_step``
- ``hydromodpy.workflow.internals.derived.DerivedRegistry``
- ``hydromodpy.workflow.runner.Pipeline``
- ``hydromodpy.workflow.steps.{ValidateStep, ResolveStep, ...,
  DisplayStep}``

The v1 ``StepsLedger`` module is removed; workflow steps are now
recorded in the project ``catalog.duckdb`` under the
``workflow_steps`` table (see :doc:`/architecture/storage-layout`).

Recommended reading path
------------------------

1. ``hydromodpy/workflow/internals/state.py``
2. ``hydromodpy/workflow/internals/step.py``
3. ``hydromodpy/workflow/runner.py``
4. ``hydromodpy/workflow/steps/__init__.py`` to see the registered
   steps.
5. one step (``hydromodpy/workflow/steps/build_geographic.py``).
6. ``hydromodpy/workflow/internals/dependencies.py`` for the
   skip-aware logic used by calibration.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``physics``,
  ``data``, ``spatial``, ``simulation``, ``solver``, ``calibration``,
  ``results``, ``display``, ``analysis``, ``reporting`` and
  ``workflow``.
- Allowed sources: ``project`` and ``cli``.

See also
--------

- :doc:`simulation` -- the simulation runner that the steps wrap.
- :doc:`calibration` -- the calibration loop that reuses
  ``earliest_affected_step``.
- :doc:`/architecture/overview/mental-model-and-design-choices` --
  the design rationale behind the workflow layer.
