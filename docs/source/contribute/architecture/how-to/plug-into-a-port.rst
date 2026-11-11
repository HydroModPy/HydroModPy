Plug into a port
================

A port is a place where HydroModPy takes a class it does not know in advance: a solver
backend, an output extractor, a data source, a trial evaluator, an optimizer, a terrain
engine, a mesh engine, an export format or a figure. Each port is one instance of
``PluginRegistry`` (``hydromodpy/core/plugin_registry.py``), so they all resolve a name the
same way. An in-tree class is a dotted path imported on first lookup, and an out-of-tree
class joins through an entry-point group, without a patch to HydroModPy.

The ports
---------

The table is read from the registries when the docs are built. Each row gives the
registry, the noun it uses in its messages, the names it serves in this build, the
entry-point group, the members a plugin declares, the README that holds the contract of the
port, and the test files that import the registry.

.. hmp-port-table::

The recipe
----------

A plugin joins a port in four steps.

1. Write the class with the members the table names for its port. The README of the port
   says what each member receives and returns, and the Protocol of the port module types
   them. ``register`` refuses a class that leaves a member out, and names it.
2. Register it. A class of this repository is a dotted path added to ``_BUILTIN_PATHS`` of
   the registry module. A class of another package publishes an entry point in the group of
   the port, named like its key in the registry, in the ``pyproject.toml`` of that package.
   The README of the port gives the form of the key, for example ``<process_type>_<name>``
   for a solver backend:

   .. code-block:: toml

      [project.entry-points."hydromodpy.mesh.engine"]
      my_engine = "my_package.engine:MyEngine"

   A key of a document that names a plugin is read by ``check_registered_name``. It
   refuses a name nothing serves with the names this installation serves and the group a
   third party joins through. An entry point that cannot be imported is refused by name,
   with its target and the reason.
3. Write the README of the port if the port is new. A port README says what the port
   receives, what it returns, the members a plugin declares, how it registers, the sentence
   that refuses a name nothing serves, and the test that covers it, in that order, in at
   most thirty lines. ``python -m tools.docs.check_readmes`` finds the ports from the code
   (the folder of each ``PluginRegistry`` instance and of each solver backend) and checks
   that each has its README.
4. Let the parametrized test take it. The suites of ``tests/ports/`` run over
   ``names()`` of their registry and never over a list written in ``tests/``, so an
   installed plugin is held to the port by the same cases as the built-in ones. Run the
   suite of the port from a clone with the plugin installed.

The figure port has no entry-point group. A figure is a ``BaseFigure`` subclass in a
public module of ``hydromodpy/display/figures/``, and the generated table
``figure_table.py``, rewritten by ``python -m tools.figure_table``, is its registration.

The two closed tables
---------------------

Two lists are tables of the code and take no plugin. The metric names are the rows of
``METRIC_SPECS`` in ``hydromodpy/core/scoring/metric_table.py``, one ``MetricSpec`` per
name, and the boundary ids are the rows of ``FLOW_BOUNDARY_DEFINITIONS`` in
``hydromodpy/model/boundaries/boundary_condition_registry.py``, one
``FlowBoundaryDefinition`` per id. A new metric or a new boundary is a row added in the
code, with its kernel or its binder. The ``Literal`` of the names a TOML may write is built
from the rows, so the name is written once and a document that writes another is refused
when it is read. The README of each folder is the contract of its table.

The recipes of one port
-----------------------

Some ports have a page of their own, with the files to create and the pitfalls:
:doc:`add-a-solver`, :doc:`add-a-data-source`, :doc:`add-a-calibration-method`,
:doc:`add-an-exporter` and :doc:`add-a-figure`. The mesh port is described in
:doc:`../mesh/mesh-engines`.
