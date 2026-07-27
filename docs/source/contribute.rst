:html_theme.sidebar_secondary.remove:

Contribute
==========

.. raw:: html

   <p class="lead">
   HydroModPy welcomes bug reports, new features, documentation work,
   and example notebooks. This page covers the contributor install,
   the coding style, the test ladder, the docs build, and the pull
   request flow.
   </p>

.. admonition:: User install
   :class: tip

   For the user install only (``pip``, ``uv``, ``conda``, ``docker``,
   solver binaries), see :doc:`install`.

Open an issue
-------------

The fastest way to help the project is to open an issue at
https://github.com/HydroModPy/HydroModPy/issues, even without writing
code. Useful issue types:

- **Bug report.** Describe what happened, what you expected, and the
  steps to reproduce. Attach the TOML config (or a minimal version) and
  the full traceback.
- **Feature request.** Describe what you need and why. If the feature
  is a new data source, attach the API endpoint, the response format,
  the variable units, the spatial and temporal resolution, and any
  rate limit.
- **New variable or format.** Specify the variable name, the physical
  unit, the temporal resolution, the spatial coverage (point or
  gridded), and the file format or API.
- **Question.** Open an issue if the documentation does not cover your
  case. The thread also helps other users with the same question.

Set up a development environment
--------------------------------

The contributor install always uses an editable clone so edits to
``.py`` files take effect on the next import without a reinstall. Pick
the recipe that matches your platform.

.. tab-set::

   .. tab-item:: pip + venv (Linux / macOS / Windows)
      :sync: dev-pip

      Lightweight setup, no conda required. Works on Python 3.11 or newer.

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         python3.12 -m venv .venv
         source .venv/bin/activate
         python -m pip install --upgrade pip
         pip install -e ".[dev,test,docs]"
         pre-commit install

      On Windows PowerShell, replace the venv lines with
      ``py -3.12 -m venv .venv`` and ``.\.venv\Scripts\Activate.ps1``.

   .. tab-item:: conda YAML
      :sync: dev-conda

      Recommended on Windows or for the curated geospatial stack.
      Three env files live in the
      `install/ folder on GitHub
      <https://github.com/HydroModPy/HydroModPy/tree/main/install>`_;
      pick the one you need.

      .. list-table::
         :header-rows: 1
         :widths: 30 60

         * - Env file
           - Purpose
         * - ``env_hydromodpy.yml``
           - Runtime stack (Spyder included). Use it when you run
             scripts and notebooks but do not edit the source tree.
             Includes the default Optuna calibration sampler.
         * - ``env_hydromodpy_pkg.yml``
           - Editable stack: same packages plus
             ``pip install -e "..[docs,docs-uml,test]"`` for local doc builds
             and test execution.
         * - ``env_hydromodpy_light_pkg.yml``
           - Smaller editable stack, recommended on Linux/WSL for
             command-line development and test execution.

      Editable env (recommended for contributors):

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         conda env create -n hmp-dev -f install/env_hydromodpy_pkg.yml
         conda activate hmp-dev
         pre-commit install

      Run the command from the repository root: the relative
      ``pip install -e "..[docs,docs-uml,test]"`` inside the YAML must reach the
      project source. The Python version is pinned by each YAML; no
      need to set it on the command line. These editable YAMLs
      preinstall ``graphviz`` and ``pygraphviz`` from ``conda-forge``
      before the editable ``pip`` step. This avoids compiling
      ``pygraphviz`` from source while installing the ``docs-uml``
      extra (``erdantic`` regenerates the config ER diagrams).

      Quick option without cloning, when you only need the runtime
      env: download ``env_hydromodpy.yml`` from the install folder
      above, then run

      .. code-block:: bash

         conda env create -n hmp -f env_hydromodpy.yml
         conda activate hmp

   .. tab-item:: Linux / WSL helper
      :sync: dev-wsl

      Ubuntu and WSL users can bootstrap the editable environment with
      the helper script shipped in ``install/``. It installs the
      minimal system dependency, creates the conda env, and adds the
      Linux runtime library needed by ``gmsh``.

      .. code-block:: bash

         bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl
         pre-commit install

      Add ``--with-petsc`` to install PETSc, ``petsc4py``, ``mpi4py``,
      and ``mpich`` inside the same env:

      .. code-block:: bash

         bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl --with-petsc

      For day-to-day work after the env exists, open one ready shell
      with the companion helper:

      .. code-block:: bash

         bash install/enter_wsl_dev.sh
         bash install/enter_wsl_dev.sh --headless          # non-interactive
         bash install/enter_wsl_dev.sh --output-root /mnt/c/Users/<user>/Documents/HydroModPyOutputs

      The helper sources conda, activates the env, and moves to the
      repository root. If conda is not yet inside WSL, Miniforge is the
      recommended bootstrap:

      .. code-block:: bash

         sudo apt update && sudo apt install -y curl git libglu1-mesa
         curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
         bash Miniforge3-Linux-x86_64.sh
         source ~/miniforge3/etc/profile.d/conda.sh

      If you create the conda env manually instead of using
      ``setup_wsl_dev.sh``, add the Linux ``gmsh`` runtime shim
      yourself:

      .. code-block:: bash

         conda install -n <env> -c conda-forge xorg-libxft

The ``-e`` (editable) flag keeps the local source tree importable from
anywhere. The ``pre-commit install`` step registers the Git hook that
runs ``ruff`` before each commit.

Available extras
~~~~~~~~~~~~~~~~

Add only what you need. They can be combined inside one ``pip install``
command, for example ``pip install -e ".[dev,test,docs]"``.

.. list-table::
   :header-rows: 1
   :widths: 18 60

   * - Extra
     - Provides
   * - ``[test]``
     - ``pytest``, ``pytest-xdist``, ``pytest-timeout``,
       ``pytest-cov``, ``coverage``, ``pyyaml``, and ``jsonschema``.
   * - ``[dev]``
     - ``ruff`` and ``pre-commit`` for linting and Git hooks.
   * - ``[docs]``
     - Sphinx, the PyData theme, ``myst-parser``, ``nbsphinx``, plus
       all extensions used to build this documentation. Pure wheels,
       no system Graphviz needed.
   * - ``[docs-uml]``
     - ``erdantic`` to regenerate the config ER diagrams. Needs a
       system Graphviz install; ``pygraphviz`` has no wheels.
   * - ``[ide]``
     - ``ipykernel``, ``jupyterlab``, Spyder, and PySide6.
   * - ``[viewer3d]``
     - ``pyvista`` for 3D mesh visualization.

After install, two CLI commands become available: ``hmp`` and
``hydromodpy``. They are aliases. Run ``hmp --help`` to list the
subcommands.

Windows + WSL split for PETSc
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The PETSc-backed Boussinesq backend is Linux only. On a Windows
workstation with WSL configured, use two environments instead of
forcing every dependency into one:

- WSL ``hydromodpy-wsl`` for PETSc simulations and numerical
  validation tests,
- Windows ``hydromodpy-kpg`` (or another docs-capable env) for the
  Sphinx build.

Run the PETSc smoke suite from PowerShell through WSL:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh"

For the Boussinesq lower-obstacle drying case only, run the dedicated
pytest target instead:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- python -m pytest tests/validation/numerical/transient/test_boussinesq_drying_petsc.py -q"

The corresponding Windows documentation build stays independent from
PETSc and only needs the Sphinx stack plus the already materialized
documentation assets:

.. code-block:: powershell

   conda run --no-capture-output -n hydromodpy-kpg python -m sphinx -E -a -W -j auto -b html docs/source docs/build/html

PETSc, MPI, and Linux solver dependencies stay in the WSL environment,
while the Windows documentation environment only needs the Sphinx stack.

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
- Reuse helpers from ``hydromodpy/core/io/`` rather than
  duplicating raster, folder, or path logic.

Run the tests
-------------

The fastest local check is ``hmp test unit``. Before merging
workflow-facing changes, also run ``hmp test regression --fast``.
On GitHub, the main CI gate runs quality checks, architecture
contracts, fast tests on Python 3.11 to 3.13, unit tests, integration
tests, fast regression tests, a wheel smoke test, and an advisory mypy
baseline. Specialized workflows cover docs, gallery artifacts, Docker,
PETSc, performance, workflow linting, and dependency audit only when
their inputs change.

For the full ladder (unit, integration, e2e, regression, validation,
MMS, solver-sanity, calibration twins) with the role of each family
and how to read a failure, use
:doc:`architecture/overview/test-families-and-quality-roles`.
For the GitHub Actions map and check-name conventions, use
:doc:`architecture/ci-workflows`.

A typical Linux/WSL non-interactive test session is:

.. code-block:: bash

   export MPLBACKEND=Agg
   python -m pytest tests/unit -q
   hmp test regression --fast -j 2
   hmp test validation --fast

Build the documentation
-----------------------

The Sphinx project lives in ``docs/source``. The ``[docs]`` extra
ships every required extension, plus PlantUML for UML diagrams.

.. code-block:: bash

   pip install -e ".[docs]"
   python tools/setup_plantuml.py
   make -C docs html

``make -C docs html`` honours the ``-j auto`` default in the Makefile,
so the recursive autosummary on ``hydromodpy`` (~900 pages) writes in
parallel rather than the 5-minute single-thread default.

On the reference Windows setup, the same build can be run from the
repository root with the documentation environment:

.. code-block:: powershell

   conda run --no-capture-output -n hydromodpy-kpg python -m sphinx -E -a -W -j auto -b html docs/source docs/build/html

``tools/setup_plantuml.py`` downloads a pinned PlantUML jar with
SHA256 verification and installs the local Graphviz bundle on Windows.
Pass ``--skip-graphviz`` if the system already provides the ``dot``
command.

The config ER diagrams are regenerated with ``erdantic``, which builds
on ``pygraphviz``. ``pygraphviz`` ships no Linux or Windows wheels and
compiles against the system Graphviz headers. Install the Graphviz
stack from conda-forge first, then add the ``docs-uml`` extra:

.. code-block:: bash

   conda install -c conda-forge graphviz pygraphviz
   python -m pip install -e ".[docs-uml]"

The plain ``[docs]`` build does not need this step. The committed SVGs
are reused when ``erdantic`` is absent.

For live preview during edits:

.. code-block:: bash

   sphinx-autobuild -E -a -b html --open-browser --watch hydromodpy --watch examples --watch tools docs/source docs/build/html

Or, when ``make`` is available:

.. code-block:: bash

   make -C docs livehtml

If the change touches the capability gallery, refresh the generated
artifacts before committing:

.. code-block:: bash

   python -m tools.doc_gallery
   python -m tools.doc_gallery --check

Auto-regenerated artifacts
~~~~~~~~~~~~~~~~~~~~~~~~~~

Two ``builder-inited`` hooks run at every Sphinx build:

- ``tools.doc_config`` regenerates ``docs/source/user_guide/config_reference/``
  (one page per top-level TOML section plus the JSON Schema and
  OpenAPI exports under ``_static/``).
- ``tools.doc_figures`` regenerates
  ``docs/source/user_guide/figures_inventory.partial.rst`` from the
  registered figure catalog in ``hydromodpy.display``.

Both regenerators use ``_write_if_changed`` (idempotent), so the
output mtime stays stable when the content has not changed and
``sphinx-autobuild`` does not loop on the regenerated files.

For tight iteration loops on RST that is not config-related, skip the
heavy regeneration with:

.. code-block:: bash

   HMP_SKIP_CONFIG_REFERENCE_GEN=1 make -C docs html

``tools.doc_figures`` remains active in that mode (its run is cheap).

Submit a pull request
---------------------

1. Branch from ``dev`` for normal work. Use a short descriptive name,
   for example ``feat/bdtopage-loader``, ``fix/calib-cell-resolve``,
   or ``docs/versioning-policy``.
2. ``main`` is the current v2 line and future default branch.
   ``archive-v1`` is the frozen v1.0.0 branch and should not receive
   normal PRs. Use ``maint/1.x`` only if active maintenance of the
   ``1.*`` line resumes. Use ``release/X.Y`` only for short stabilization
   windows before a final ``vX.Y.0`` release.
3. Group related changes in one focused commit. Follow Conventional
   Commits: one line, no body. Examples:
   ``feat(data): add bdtopage loader``,
   ``fix(calibration): resolve structured cells``, or
   ``docs(versioning): document maintenance branches``.
4. Push the branch and open a pull request against ``dev``. Reference
   the related issue (``Closes #123``) when applicable.
5. Mention reviewers if the change affects modelling outputs, the
   public API, or any user-visible workflow.

Releases are identified by tags such as ``v1.1.0``, ``v2.0.0a1``,
``v2.0.0b1``, or ``v2.0.0rc1``, not by branch names. The full branch,
tag, pre-release, changelog, and GitHub Release policy is documented in
:doc:`about/release_policy`.

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
- :doc:`user_guide/workflows/index` lists the supported user APIs
  (CLI, TOML, Python, notebook) and the seven driving modes.
