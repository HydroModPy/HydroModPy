Project lifecycle
=================

:class:`hydromodpy.project.Project` is the setup-once, run-many entry
point. It validates the configuration, builds the geographic/domain
context, loads the declared data, generates the mesh, then exposes
``run`` and ``calibrate`` for repeated launches.

Construction
------------

Two construction modes are supported:

- **Eager** (default): the model phase runs as part of ``__init__``. The
  caller gets a project ready to ``run``.
- **Lazy**: only the configuration is validated. The caller drives the
  model phase manually with :meth:`Project.build_geographic`,
  :meth:`Project.load_data`, :meth:`Project.build_mesh`.

.. code-block:: python

   import hydromodpy as hmp

   eager = hmp.Project("hydromodpy.toml")
   lazy = hmp.Project.lazy("hydromodpy.toml")

Alternate classmethods build a project from a payload that is not on
disk: :meth:`Project.from_toml`, :meth:`Project.from_json`,
:meth:`Project.from_dict`, :meth:`Project.rerun`.

Lifecycle as context manager
----------------------------

A project owns a DuckDB catalog handle and a few cached preprocessing
files. The recommended pattern is to use it as a context manager so
:meth:`Project.close` runs even when an exception is raised:

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project.lazy("hydromodpy.toml") as p:
       p.setup_workspace()
       p.build_geographic()
       p.load_data()
       p.build_mesh()
       run = p.run(name="baseline", Sy=0.05)

Three concerns
--------------

The public surface of :class:`Project` splits into three concerns:

1. **Factory and lifecycle**: constructors, context manager,
   :meth:`Project.close`, ``__repr__``, and inspection properties
   (``data``, ``runs``, ``cfg``, ``geographic``, ``domain``, ``store``,
   ``time_grid``, ``loaded_data``, ``workflow_context``, ``has_mesh``,
   ``data_loaded``, ``__getitem__``).
2. **Model phase**: :meth:`Project.setup_workspace`,
   :meth:`Project.build_geographic`, :meth:`Project.rebuild_geographic`,
   :meth:`Project.load_data`, :meth:`Project.reload_data`,
   :meth:`Project.build_mesh`.
3. **Run phase**: :meth:`Project.run`, :meth:`Project.calibrate`, and the
   prepared-run helper :meth:`Project.session` returning a
   :class:`hydromodpy.project.session.ProjectSession`.

Removed in the T1 interface refactor
------------------------------------

The methods ``Project.overview``, ``Project.compare``, ``Project.mesh``
and ``Project.report`` were removed. These workflows do not benefit from
setup-once state, so they now live on the functional facade only:

- ``hmp.overview(toml)``
- ``hmp.compare(toml)``
- ``hmp.mesh(toml)``
- ``hmp.report(session_id)``

Use :class:`Project` for repeated simulations and calibration; use
:mod:`hydromodpy._api` verbs for the one-shot TOML workflows above.
