Contribute
==========

HydroModPy is open to bug reports, new features, documentation work, and
example notebooks. This page describes the practical steps. The
:doc:`user_guide/config_reference/index` covers the configuration system
section by section, :doc:`user_guide/data/index` describes the data
managers, and :doc:`user_guide/concepts/project-vs-run` explains the TOML
inheritance contract.

Open an issue
-------------

The fastest way to help the project is to open an issue at
https://github.com/HydroModPy/HydroModPy/issues, even without writing
code. Useful issue types:

- **Bug report.** Describe what happened, what you expected, and the
  steps to reproduce. Attach the TOML config (or a minimal version) and
  the full traceback.
- **Feature request.** Describe what you need and why. If the feature is
  a new data source, attach the API endpoint, the response format, the
  variable units, the spatial and temporal resolution, and any rate
  limit.
- **New variable or format.** Specify the variable name, the physical
  unit, the temporal resolution, the spatial coverage (point or
  gridded), and the file format or API.
- **Question.** Open an issue if the documentation does not cover your
  case. The thread also helps other users with the same question.

Set up a development environment
--------------------------------

Use an editable install in a fresh Python environment. Pick conda or
``venv``, then add the extras you need.

.. code-block:: bash

   git clone https://github.com/HydroModPy/HydroModPy.git
   cd HydroModPy
   conda create -n hmp-dev python=3.12 -y
   conda activate hmp-dev
   pip install -e ".[dev,test,docs]"
   pre-commit install

The ``-e`` flag (editable) links the installed package to the local
source tree. Edits to ``.py`` files take effect on the next import
without a reinstall. The ``pre-commit install`` step registers the Git
hook that runs ``ruff`` before each commit.

Available extras
~~~~~~~~~~~~~~~~

Add only the extras you need. They can be combined inside the same
``pip install`` command, for example ``pip install -e ".[dev,test]"``.

.. list-table::
   :header-rows: 1
   :widths: 18 60

   * - Extra
     - Provides
   * - ``[test]``
     - ``pytest``, ``pytest-xdist``, ``pytest-timeout``, ``coverage``.
   * - ``[dev]``
     - ``ruff`` and ``pre-commit`` for linting and Git hooks.
   * - ``[docs]``
     - Sphinx, the RTD theme, ``myst-parser``, ``nbsphinx``, plus all
       extensions used to build this documentation.
   * - ``[ide]``
     - ``ipykernel``, ``jupyterlab``, Spyder, and PySide6.
   * - ``[viewer3d]``
     - ``pyvista`` for 3D mesh visualization.

After install, two CLI commands become available: ``hmp`` and
``hydromodpy``. They are aliases. Run ``hmp --help`` to list the
subcommands.

Coding style
------------

- Target Python 3.11 or newer. Type hints are encouraged on public
  signatures.
- Format and lint with ``ruff``. The repository ships a pinned
  configuration in ``pyproject.toml``:

  .. code-block:: bash

     ruff check .
     ruff format .

- The pre-commit hook runs ``ruff`` automatically on staged files. If
  the hook reports issues, fix them and stage the files again before
  retrying the commit.
- Add a docstring on every public method and class. Keep parameter
  names consistent with the existing modules.
- Reuse helpers from ``hydromodpy/core/tools/`` rather than duplicating
  raster, folder, or path logic.

Run the tests
-------------

The fastest local check is ``hmp test unit``. Before merging
workflow-facing changes, also run ``hmp test regression --fast``.

For the full ladder (unit, integration, e2e, regression, validation,
MMS, solver-sanity, calibration twins) with the role of each family
and how to read a failure, use
:doc:`architecture/overview/test-families-and-quality-roles`.

The PETSc Boussinesq backend is Linux only. On a Windows workstation
with WSL configured, run PETSc-backed simulations in WSL and keep the
Windows environment for documentation builds:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh"

This avoids adding PETSc, MPI, or ``petsc4py`` as implicit
requirements of the Sphinx build.

Build the documentation
-----------------------

The Sphinx project lives in ``docs/source``. The ``[docs]`` extra
ships every required extension.

.. code-block:: bash

   pip install -e ".[docs]"
   python tools/setup_plantuml.py
   cd docs
   python -m sphinx -E -a -W -b html source build/html

On the reference Windows setup, the same build can be run directly from the
repository root with the documentation environment:

.. code-block:: powershell

   conda run --no-capture-output -n hydromodpy-kpg python -m sphinx -E -a -W -b html docs/source docs/build/html

``tools/setup_plantuml.py`` downloads a pinned PlantUML jar with SHA256
verification and installs the local Graphviz bundle on Windows. Pass
``--skip-graphviz`` if the system already provides the ``dot`` command.

For live preview during edits:

.. code-block:: bash

   sphinx-autobuild -E -a docs/source docs/_build/html

If the change touches the capability gallery, refresh the generated
artifacts before committing:

.. code-block:: bash

   python -m tools.doc_gallery
   python -m tools.doc_gallery --check

Submit a pull request
---------------------

1. Branch from ``dev`` (not ``master``). Use a short descriptive name,
   for example ``feature/add-bdtopage-loader`` or
   ``fix/calib-cell-resolve``.
2. Group related changes in one focused commit. Follow the repository
   commit format ``[scope] - short summary in lowercase``. Examples:
   ``[docs] - update install extras for v0.5``,
   ``[calibration] - fix structured cell resolution``.
3. Push the branch and open a pull request against ``dev``. Reference
   the related issue (``Closes #123``) when applicable.
4. Mention reviewers if the change affects modelling outputs, the
   public API, or any user-visible workflow.

Releases move from ``dev`` to ``master`` once the notebooks run without
warnings, the changelog is updated, and a tag is pushed.

Where to look next
------------------

- :doc:`user_guide/config_reference/index` is the deep reference for
  every TOML section, with field types, defaults, validators, and the
  ``ParamLevel`` / ``VisibleWhen`` rules used to declare new fields.
- :doc:`user_guide/data/index` covers the data managers (variables,
  providers, cache, custom data format).
- :doc:`user_guide/concepts/workspace-layout` and
  :doc:`user_guide/concepts/project-vs-run` document the workspace
  layout and the TOML inheritance contract.
- :doc:`architecture/index` documents the package layout and the
  runtime handoff between modules.
- :doc:`user_guide/driving-hydromodpy` lists the supported user APIs
  (CLI, TOML, Python, notebook).
