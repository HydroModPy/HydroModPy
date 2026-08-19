Troubleshooting
===============

Look up the error message you saw to find its likely cause and fix.
Each entry lists the message verbatim, the root cause, and the
recommended action.

If your error is not listed, open a GitHub issue with the full traceback,
the TOML config (or its schema), and the version of HydroModPy
(``hmp --version``).

Configuration parsing
---------------------

.. dropdown:: ``Unknown top-level TOML section(s): ...``
   :icon: alert

   **Cause.** The TOML root contains a section name that is not part of
   the validated ``HydroModPyConfig`` schema. The live list of valid
   sections is enumerated at :doc:`config_reference/index`.

   **Fix.** Rename or remove the offending section. Check spelling and
   underscores against the section index, then re-run ``hmp config check
   <file>.toml``.

.. dropdown:: ``constraints_mode is required``
   :icon: alert

   **Cause.** ``[mesh_catchment]`` was loaded without
   ``constraints_mode``.

   **Fix.** Set ``constraints_mode`` to one of ``geology_only``,
   ``rivers_only``, or ``geology_rivers``.

.. dropdown:: ``geology section is required when constraints_mode includes geology``
   :icon: alert

   **Cause.** ``mesh_catchment.constraints_mode`` references geology but
   ``[mesh_catchment.geology]`` is missing.

   **Fix.** Add a ``[mesh_catchment.geology]`` block describing the
   polygon source, or switch ``constraints_mode`` to ``rivers_only``.

.. dropdown:: ``unknown config section ...``
   :icon: alert

   **Cause.** ``hmp config schema --section <name>`` was called with a
   section name that is not part of the schema export map.

   **Fix.** Run ``hmp config schema --help`` to list valid section
   names.

.. dropdown:: ``[analysis] must be a mapping``
   :icon: alert

   **Cause.** The TOML emitted ``[analysis]`` as a primitive (string,
   number) instead of a mapping table.

   **Fix.** Re-emit the section as ``[analysis]`` followed by sub-keys
   (or as ``[analysis.batch]`` etc.).

Solver binaries
---------------

.. dropdown:: ``MODFLOW binary missing`` (or platform-specific equivalent)
   :icon: gear

   **Cause.** The first solver run could not locate the MODFLOW 6 or
   MODFLOW-NWT executable in ``~/.cache/hydromodpy/bin/``.

   **Fix.** Run ``hmp install-binaries`` once. The toolbox downloads
   the binaries lazily; this command forces the download for the
   current platform.

.. dropdown:: ``Could not find a valid PETSc installation``
   :icon: gear

   **Cause.** A Boussinesq run requested the ``petsc`` runtime backend
   but PETSc/petsc4py is not installed in the environment.

   **Fix.** Either install PETSc with ``conda install -c conda-forge
   petsc4py``, or set ``[flow] runtime_backend = "scipy_sparse"`` to
   use the pure-Python backend.

Data and storage
----------------

.. dropdown:: ``payload_dir not found`` / ``Zarr store not found at ...``
   :icon: database

   **Cause.** A run is trying to read a cached geographic payload or a
   Zarr field store that has not been produced yet (or has been
   deleted).

   **Fix.** Re-run the upstream stage that produces the artifact
   (``overview`` for geographic preprocessing, ``simulation`` for the
   Zarr field store). Check ``workspace.project_root`` for stale
   cache directories.

.. dropdown:: ``No .hmp archive at ...``
   :icon: database

   **Cause.** ``hmp data import <path>`` was pointed at a missing or moved
   ``.hmp`` archive.

   **Fix.** Confirm the archive path. ``hmp catalog export <ref> -o
   <file>.hmp`` prints the archive it wrote; that path is the one
   ``hmp data import`` expects.

.. dropdown:: ``CSV time series not found`` / ``NetCDF file not found``
   :icon: database

   **Cause.** An importer was called on a path that does not exist
   relative to the TOML location.

   **Fix.** Check the path. Relative paths resolve against the TOML
   file directory; absolute paths and ``~`` expansion are also
   honored.

Calibration and runtime
-----------------------

.. dropdown:: ``Install the calibration extra for cma_es or Optuna CMA-ES``
   :icon: zap

   **Cause.** ``[calibration] method`` was set to ``cma_es`` or
   ``[calibration.optimizer_kwargs] sampler = "cmaes"`` for ``optuna``,
   but the optional CMA-ES dependencies are not installed. The default
   ``optuna`` TPE sampler is installed by the base package.

   **Fix.** Run ``pip install -e ".[calibration]"`` or
   ``conda install -c conda-forge cma cmaes`` and retry.

.. dropdown:: ``mode must be one of: family_priority_local_budget, grid_local_budget``
   :icon: alert

   **Cause.** ``[mesh_catchment.zone_meshing.refinement_policy] mode``
   was set to an unknown string.

   **Fix.** Use one of the two allowed modes. See
   :doc:`config_reference/mesh_catchment`.

.. dropdown:: ``output paths cannot be empty when provided``
   :icon: alert

   **Cause.** A ``[mesh_catchment]`` output path field
   (``output_mesh``, ``output_summary_json``, ``output_figure``,
   ``output_figure_regional``) was set to an empty string.

   **Fix.** Either remove the field to fall back to the default path,
   or provide a non-empty path.

Build and documentation
-----------------------

.. dropdown:: Sphinx build hangs or feels stuck on autosummary
   :icon: rocket

   **Cause.** Sphinx is single-threaded by default and the recursive
   autosummary on ``hydromodpy`` produces ~900 pages.

   **Fix.** Always invoke Sphinx with ``-j auto`` (``make -C docs html``
   already does this; the Makefile defaults
   ``SPHINXOPTS ?= -j auto``).

Reporting a new error
---------------------

If you hit an error that is not listed above, please file a GitHub
issue under the ``HydroModPy/HydroModPy`` repository with:

- the full traceback,
- the TOML config (or a minimal reproduction),
- the output of ``hmp --version``.
