Workflow And Pipeline API
=========================

Generated reference for simulation planning, workflow context, pipeline states,
steps, and derived computation contracts.

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

   ~hydromodpy.pipeline.Pipeline
   ~hydromodpy.pipeline.PipelineState
   ~hydromodpy.pipeline.Step
   ~hydromodpy.pipeline.DerivedRegistry
   ~hydromodpy.pipeline.ResolvedState
   ~hydromodpy.pipeline.LoadedState
   ~hydromodpy.pipeline.MeshedState
   ~hydromodpy.pipeline.SolverRanState
   ~hydromodpy.pipeline.ExtractedState
   ~hydromodpy.pipeline.DerivedState
   ~hydromodpy.pipeline.ExportedState
