How-to Recipes
==============

This section answers prescriptive questions of the form "I want to add
X, where does it go and what contract must I honour?".

Each recipe lists:

- the **files** to create or edit;
- the **contract** to honour (Pydantic model, Protocol, registry);
- the **registration** mechanism (entry point or in-process call);
- the **test** to add and the command to run;
- the **pitfalls** that the layer matrix or the linter would flag.

For a deeper code reading, follow the link to the matching
:doc:`../packages/index` entry.

Recipes
-------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Add a solver
      :link: add-a-solver
      :link-type: doc

      Bind a new ``(process_type, solver_name)`` pair to a backend
      adapter and an output extractor.

   .. grid-item-card:: Add a process
      :link: add-a-process
      :link-type: doc

      Introduce a new ``ProcessSpatial`` runtime alongside ``Flow``
      and ``Transport``.

   .. grid-item-card:: Add a config field
      :link: add-a-config-field
      :link-type: doc

      Extend a Pydantic section with a new field, with units and a
      ``Profile`` annotation.

   .. grid-item-card:: Add a data variable
      :link: add-a-data-variable
      :link-type: doc

      Wire a new family (next to ``hydrometry``, ``geology``, ``dem``,
      etc.) and its manager.

   .. grid-item-card:: Add a data source
      :link: add-a-data-source
      :link-type: doc

      Plug a new public API or local-file source into an existing
      data variable.

   .. grid-item-card:: Add a figure
      :link: add-a-figure
      :link-type: doc

      Publish a named figure consumable by ``Run.plot`` and the
      ``[display]`` section.

   .. grid-item-card:: Add a block HTML report
      :link: add-a-block-html-report
      :link-type: doc

      Compose a static HTML report from reusable blocks, figures,
      metrics, tables, and artifact links.

   .. grid-item-card:: Add an exporter
      :link: add-an-exporter
      :link-type: doc

      Stream catalog rows or per-run payloads into a new file format.

   .. grid-item-card:: Add a test
      :link: add-a-test
      :link-type: doc

      Pick the right test family and the right pytest marker.

   .. grid-item-card:: Add a CLI command
      :link: add-a-cli-command
      :link-type: doc

      Register a new ``hmp`` verb under ``cli/commands/``.

   .. grid-item-card:: Add a calibration method
      :link: add-a-calibration-method
      :link-type: doc

      Plug a new optimizer into the ask/tell engine.

   .. grid-item-card:: Build a frontend
      :link: build-a-frontend
      :link-type: doc

      Consume the JSON Schema and the partial-validator for any UI
      (Streamlit, Angular, React, Jupyter widget).

.. toctree::
   :hidden:
   :maxdepth: 1

   add-a-solver
   add-a-process
   add-a-config-field
   add-a-data-variable
   add-a-data-source
   add-a-figure
   add-a-block-html-report
   add-an-exporter
   add-a-test
   add-a-cli-command
   add-a-calibration-method
   build-a-frontend
