Contribute
==========

HydroModPy is open to bug reports, new features, documentation work, and
example notebooks. This page describes the practical steps. The deep
reference for the configuration system, the data managers, and the TOML
inheritance rules is kept in ``CONTRIBUTING.md`` at the repository root.

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

HydroModPy uses several test families because they do not validate the same
thing:

- ``tests/unit/`` covers API and behaviour checks on isolated
  components.
- ``tests/integration/`` covers cross-module workflows without golden
  references.
- ``tests/e2e/`` covers complete user-facing scenarios.
- ``tests/regression/`` checks reference outputs and full workflows.
- ``tests/validation/`` runs scientific benchmarks against analytical or
  trusted physical references.

Quick command ladder:

.. code-block:: bash

   hmp test unit
   pytest tests/integration -q
   pytest tests/e2e -q
   hmp test regression --fast -j 2
   hmp test regression --extensive
   hmp test validation --fast
   hmp test validation --steady
   hmp test validation --transient
   pytest -m solver_sanity -q
   pytest -m petsc -q
   python -m validation_cases.run_cases --solver modflownwt --regime both --no-show

For the detailed role of each family, and for guidance on how to interpret one
failure, use
:doc:`architecture/overview/test-families-and-quality-roles`.

The PETSc Boussinesq backend is Linux only. Tests tagged
``pytest.mark.petsc`` are skipped on Windows by design.

On a Windows workstation with WSL configured, keep the numerical and
documentation environments separate. Run PETSc-backed simulations in WSL:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh"

and keep the Windows environment for documentation builds. This avoids adding
PETSc, MPI, or ``petsc4py`` as implicit requirements of the Sphinx build.

Build the documentation
-----------------------

The Sphinx project lives in ``docs/readthedocs``. The ``[docs]`` extra
ships every required extension.

.. code-block:: bash

   pip install -e ".[docs]"
   python tools/setup_plantuml.py
   cd docs/readthedocs
   python -m sphinx -E -a -W -b html source _build/html

On the reference Windows setup, the same build can be run directly from the
repository root with the documentation environment:

.. code-block:: powershell

   conda run --no-capture-output -n hydromodpy-kpg python -m sphinx -E -a -W -b html docs/readthedocs/source docs/readthedocs/build/html

``tools/setup_plantuml.py`` downloads a pinned PlantUML jar with SHA256
verification and installs the local Graphviz bundle on Windows. Pass
``--skip-graphviz`` if the system already provides the ``dot`` command.

For live preview during edits:

.. code-block:: bash

   sphinx-autobuild -E -a docs/readthedocs/source docs/readthedocs/_build/html

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

- ``CONTRIBUTING.md`` (repository root) holds the deep reference for
  the CLI subcommands, the workspace layout, the TOML inheritance
  rules, the data managers, and the Pydantic config-system internals
  (``ParamLevel``, ``VisibleWhen``, validators, declaring a new config
  field).
- :doc:`architecture/index` documents the package layout and the
  runtime handoff between modules.
- :doc:`seven-modes` lists the supported user APIs (CLI, TOML, Python,
  notebook).
