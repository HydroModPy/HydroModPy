Project lifecycle
=================

:class:`hydromodpy.project.Project` is the setup-once, run-many entry
point. It validates the configuration, builds the geographic/domain
context, loads the declared data, generates the mesh, then exposes
``simulate`` and ``calibrate`` for repeated launches.

Construction
------------

Construction is cheap: ``__init__`` validates the configuration and does
no I/O. The heavy model phase builds lazily on the first
:meth:`Project.simulate` call (or any accessor), or eagerly via
:meth:`Project.prepare` and the phase verbs
(:meth:`Project.build_geographic`, :meth:`Project.load_data`,
:meth:`Project.build_mesh`).

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("project.toml")

The constructor is polymorphic: it accepts a path, a
:class:`~hydromodpy.config.HydroModPyConfig`, a ``dict``, or a JSON
string (auto-detected). :meth:`Project.rerun` re-launches a new
simulation from a persisted run snapshot.

Lifecycle as context manager
----------------------------

A project owns a DuckDB catalog handle and a few cached preprocessing
files. The recommended pattern is to use it as a context manager so
:meth:`Project.close` runs even when an exception is raised:

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project("project.toml") as p:
       p.setup_workspace()
       p.build_geographic()
       p.load_data()
       p.build_mesh()
       run = p.simulate(name="baseline", Sy=0.05)

Three concerns
--------------

The public surface of :class:`Project` splits into three concerns:

1. **Factory and lifecycle**: constructors, context manager,
   :meth:`Project.close`, ``__repr__``, and inspection properties
   (``data``, ``runs``, ``config``, ``geographic``, ``domain``, ``store``,
   ``time_grid``, ``loaded_data``, ``workflow_context``, ``has_mesh``,
   ``data_loaded``, ``__getitem__``).
2. **Model phase**: :meth:`Project.setup_workspace`,
   :meth:`Project.build_geographic`, :meth:`Project.rebuild_geographic`,
   :meth:`Project.load_data`, :meth:`Project.reload_data`,
   :meth:`Project.build_mesh`.
3. **Run phase**: :meth:`Project.simulate` and :meth:`Project.calibrate`.
   A sweep is a plain loop over :meth:`Project.simulate`::

      for v in values:
          project.simulate(name=f"Sy_{v}", Sy=v)

Removed in the T1 interface refactor
------------------------------------

The methods ``Project.overview``, ``Project.compare``, ``Project.mesh``
and ``Project.report`` were removed. These workflows do not benefit from
setup-once state, so they now run through :func:`hmp.run` on the
``[workflow] mode`` selector:

- overview: ``hmp.run(toml)`` with ``[workflow] mode="overview"``
- compare: ``hmp.run(toml)`` with ``[workflow] mode="compare"``
- mesh: ``hmp.run(toml)`` with ``[workflow] mode="mesh"``

Use :class:`Project` for repeated simulations and calibration; use
:func:`hmp.run` for the one-shot TOML workflows above.
