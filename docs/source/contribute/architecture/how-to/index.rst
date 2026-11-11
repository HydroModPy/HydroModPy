Recipes
=======

Each recipe answers "I want to add X: where does it go and what contract must I
honor?". It lists the files to create or edit, the contract (a Pydantic model,
a Protocol, a registry), the registration, the test to add and the pitfalls the
layer matrix or the linter would flag. For a deeper read of the code, follow the
link to the matching entry of :doc:`../packages/index`.

New here? Start with the :doc:`/contribute/quick-start`.

Extend the code
---------------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Plug into a port
      :link: plug-into-a-port
      :link-type: doc

      Every port with what a plugin declares, how it registers and the tests that
      cover it, read from the registries. Start here for a solver, a mesh or terrain
      engine, a data source, an evaluator, an optimizer, an export format or a figure.

   .. grid-item-card:: Add a config field
      :link: add-a-config-field
      :link-type: doc

      A field with a unit, a profile and a description. The generated reference
      documents it from that declaration.

   .. grid-item-card:: Add a solver
      :link: add-a-solver
      :link-type: doc

      Bind a ``<process_type>_<name>`` key to an adapter class that declares its
      twelve attributes, and to an output extractor.

   .. grid-item-card:: Add a process
      :link: add-a-process
      :link-type: doc

      A new process type next to flow and transport, on the worked example
      of transport.

   .. grid-item-card:: Add a data variable
      :link: add-a-data-variable
      :link-type: doc

      A new family next to ``hydrometry``, ``geology`` or ``dem``, with its
      manager.

   .. grid-item-card:: Add a data source
      :link: add-a-data-source
      :link-type: doc

      A public API or a local-file source for an existing data variable.

   .. grid-item-card:: Add a figure
      :link: add-a-figure
      :link-type: doc

      A named figure for ``Run.figure`` and the ``[display]`` section.

   .. grid-item-card:: Add a block HTML report
      :link: add-a-block-html-report
      :link-type: doc

      A static HTML report composed of reusable blocks.

   .. grid-item-card:: Add an exporter
      :link: add-an-exporter
      :link-type: doc

      Stream catalog rows or per-run payloads into a new file format.

   .. grid-item-card:: Add a CLI command
      :link: add-a-cli-command
      :link-type: doc

      A new ``hmp`` verb under ``cli/commands/``.

   .. grid-item-card:: Add a calibration method
      :link: add-a-calibration-method
      :link-type: doc

      A new optimizer in the ask/tell engine.

   .. grid-item-card:: Build a frontend
      :link: build-a-frontend
      :link-type: doc

      The JSON Schema and the partial validator, for any UI.

   .. grid-item-card:: Serve over HTTP
      :link: serve-over-http
      :link-type: doc

      The thin HTTP layer of the repository: one space per organisation, one
      process per run.

Check and ship
--------------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Add a test
      :link: add-a-test
      :link-type: doc

      The tier, the marker, the fixtures, and the rules for running tests in
      parallel.

   .. grid-item-card:: Fix a failing architecture gate
      :link: fix-an-architecture-gate
      :link-type: doc

      What each rule of ``tests/unit/architecture`` means and how to satisfy it.

   .. grid-item-card:: Cut a release
      :link: cut-a-release
      :link-type: doc

      Version, changelog, tag, and what the tag starts.

.. toctree::
   :hidden:
   :maxdepth: 1

   plug-into-a-port
   add-a-config-field
   add-a-solver
   add-a-process
   add-a-data-variable
   add-a-data-source
   add-a-figure
   add-a-block-html-report
   add-an-exporter
   add-a-cli-command
   add-a-calibration-method
   build-a-frontend
   serve-over-http
   add-a-test
   fix-an-architecture-gate
   cut-a-release
