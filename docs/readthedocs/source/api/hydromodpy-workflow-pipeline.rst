Simulation, Workflow, and Pipeline API
======================================

Simulation planning and explicit pipeline orchestration surfaces.

Simulation planning
-------------------

.. autosummary::
   :nosignatures:
   :toctree: generated/workflow-pipeline

   ~hydromodpy.simulation.SimulationConfig
   ~hydromodpy.simulation.SimulationPlan
   ~hydromodpy.simulation.SimulationPlanner
   ~hydromodpy.simulation.SimulationProcessConfig
   ~hydromodpy.simulation.SimulationTimeConfig
   ~hydromodpy.simulation.ProcessRun
   ~hydromodpy.simulation.RunContext
   ~hydromodpy.simulation.RunExecutionResult

Workflow context
----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/workflow-pipeline

   ~hydromodpy.workflow.WorkflowContext

Explicit pipeline
-----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/workflow-pipeline

   ~hydromodpy.workflow.runner.Pipeline
   ~hydromodpy.workflow.internals.state.PipelineState
   ~hydromodpy.workflow.internals.step.Step
   ~hydromodpy.workflow.internals.derived.DerivedComputation
   ~hydromodpy.workflow.internals.derived.DerivedRegistry
   ~hydromodpy.workflow.internals.state.ResolvedState
   ~hydromodpy.workflow.internals.state.LoadedState
   ~hydromodpy.workflow.internals.state.MeshedState
   ~hydromodpy.workflow.internals.state.SetupState
   ~hydromodpy.workflow.internals.state.OpenStoreState
   ~hydromodpy.workflow.internals.state.SolverRanState
   ~hydromodpy.workflow.internals.state.ExtractedState
   ~hydromodpy.workflow.internals.state.DerivedState
   ~hydromodpy.workflow.internals.state.ExportedState
