Plug into a port
================

A port is a place where HydroModPy takes a class it does not know in advance: a solver
backend, an output extractor, a data source, a trial evaluator, an optimizer, a terrain
engine, a mesh engine, an export format or a figure. Each port is one instance of
``PluginRegistry`` (``hydromodpy/core/plugin_registry.py``), so they all resolve a name the
same way.

The ports
---------

The table is read from the registries when the docs are built. Each row gives the
registry, the noun it uses in its messages, the names it serves in this build, the
entry-point group, the members a plugin declares, the README that holds the contract of the
port, and the test files that import the registry.

.. hmp-port-table::

How a plugin is registered
--------------------------

A registry looks a name up in three steps. It serves the classes registered by hand.
Then it imports the dotted path of that name from its table of built-in paths,
a ``_BUILTIN_PATHS`` dict of ``"<module>:<Class>"`` strings in the registry module.
Last, if the name is still unknown, it scans its entry-point group once and loads every
class declared there. Nothing is imported before a lookup asks for it.

So there are two ways in. A class of this repository is one line in the
``_BUILTIN_PATHS`` table of its registry module. A class of another package publishes an
entry point in the group of the port, in the ``pyproject.toml`` of that package. The name
of the entry point is the key of the class in the registry:

.. code-block:: toml

   [project.entry-points."hydromodpy.mesh.engine"]
   my_engine = "my_package.engine:MyEngine"

The registry never splits a key. It joins the id attributes of the loaded class with
``_`` and compares the result with the entry-point name. A solver of key
``flow_mysolver`` is the ``process_type`` ``flow`` and the ``name`` ``mysolver``, and a
name that holds an underscore, such as ``modflow_nwt``, stays whole. An entry point named like a built-in is ignored with a
warning, two entry points that name different targets for one key are refused by name,
and an entry point that cannot be imported is refused with its target and the reason.

The groups, read from the registry modules, are:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Group
     - Registry
   * - ``hydromodpy.solver``
     - ``solvers`` (``solver/base/registry.py``)
   * - ``hydromodpy.solver.extractor``
     - ``extractors`` (same file)
   * - ``hydromodpy.data.source``
     - ``data_sources`` (``data/source/registry.py``)
   * - ``hydromodpy.calibration.optimizer``
     - ``optimizers`` (``calibration/optim/optimizer.py``)
   * - ``hydromodpy.calibration.evaluator``
     - ``evaluators`` (``calibration/evaluation/registry.py``)
   * - ``hydromodpy.mesh.engine``
     - ``mesh_engines`` (``mesh/registry.py``)
   * - ``hydromodpy.terrain.engine``
     - ``terrain_engines`` (``catchment/terrain/registry.py``)
   * - ``hydromodpy.export.format``
     - ``export_formats`` (``results/exporters/registry.py``)

``register`` refuses a class that leaves out a member the port table names, and says
which. A key of a document that names a plugin is read by ``check_registered_name``. It
refuses a name nothing serves, lists the names this installation serves and gives the
group a third party joins through.

Steps for a new class
---------------------

1. Write the class with the members the port table names. The README of the port says what
   each member receives and returns, and the Protocol of the port module types them.
2. Register it as above. The README of the port gives the form of the key.
3. If the port is new, write its README. ``python -m tools.docs.check_readmes`` finds the
   ports from the code and checks that each has one.
4. Run the suite of the port. The tests of ``tests/ports/`` run over ``names()`` of their
   registry, never over a list written in ``tests/``, so an installed plugin meets the same
   cases as a built-in one.

The figure port has no entry-point group. A figure is a request. A new kind of plot is a
frame in ``hydromodpy/display/frames/``, and a new named request is a preset of
``hydromodpy/display/presets.py``.

The two closed tables
---------------------

Two lists are tables of the code and take no plugin. The metric names are the rows of
``METRIC_SPECS`` in ``hydromodpy/core/scoring/metric_table.py``, one ``MetricSpec`` per
name, and the boundary ids are the rows of ``FLOW_BOUNDARY_DEFINITIONS`` in
``hydromodpy/model/boundaries/boundary_condition_registry.py``, one
``FlowBoundaryDefinition`` per id. A new metric or a new boundary is a row added in the
code, with its kernel or its binder. The ``Literal`` of the names a TOML may write is built
from the rows, so a document that writes another name is refused when it is read. The
README of each folder is the contract of its table.

See also
--------

Recipes of one port:
:doc:`add-a-solver`, :doc:`add-a-data-source`, :doc:`add-a-calibration-method`,
:doc:`add-an-exporter` and :doc:`add-a-figure`. The mesh port is described in
:doc:`../engines/mesh-engines`.
