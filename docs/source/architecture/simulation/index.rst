Simulation Architecture
=======================

.. raw:: html

   <p class="lead">
   Software architecture of the simulation orchestration layer in
   ``hydromodpy.simulation``. The public entry point is the
   ``Project`` facade in ``hydromodpy/project/facade.py``, instantiated by
   ``hmp run`` or by user Python code.
   </p>

Use this section when you want the static orchestration model, the
execution-time cycle inside the simulation layer, or a code-oriented
walkthrough from TOML to solver outputs.

Pages
-----

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: TOML to solver walkthrough
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: toml-to-solver-walkthrough
      :link-type: doc

      Step-by-step trace of a TOML config from parsing through
      planner expansion, runner dispatch, and solver invocation.

   .. grid-item-card:: Orchestration class diagram
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulation-orchestration-class-diagram
      :link-type: doc

      Static UML view of the planner, runner, adapter, and
      ``Project`` facade relationships.

   .. grid-item-card:: Time-cycle diagrams
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulation-time-cycle-diagrams
      :link-type: doc

      Execution-time sequence diagrams for steady and transient
      runs, including checkpointing.

   .. grid-item-card:: Comparison workflow internals
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: comparison-workflow
      :link-type: doc

      Code orchestration behind ``[workflow].mode = "comparison"``:
      child-config generation, audit logic, observable extraction.

   .. grid-item-card:: Testbed workflow architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: testbed-workflow-architecture
      :link-type: doc

      Variant matrix expansion, child runner delegation, and the
      evidence-gathering contract used by mesh and flow testbeds.

.. toctree::
   :hidden:
   :maxdepth: 1

   toml-to-solver-walkthrough
   simulation-orchestration-class-diagram
   simulation-time-cycle-diagrams
   comparison-workflow
   testbed-workflow-architecture
