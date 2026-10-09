Contributor handbook
====================

.. rst-class:: lead

How to report a problem, set up a development environment, follow the coding
style, run the tests and send a change. For a ten-minute path from a clone to
a first commit, start with :doc:`quick-start`.

.. admonition:: User install
   :class: tip

   For the user install only (``pip``, ``uv``, ``conda``, ``docker``, solver
   binaries), see :doc:`/get-started/install`.

Open an issue
-------------

The fastest way to help is an issue at
https://github.com/HydroModPy/HydroModPy/issues, even without code.

- **Bug report.** What happened, what you expected, the steps to reproduce.
  Attach the TOML file (or a minimal version), the full traceback, the output
  of ``hmp --version``, the Python version and the operating system.
- **Feature request.** What you need and why. For a new data source or
  variable, attach the API endpoint, the response format, the units, the
  spatial and temporal resolution and any rate limit.
- **Question.** If the documentation does not cover your case, open an issue.
  The thread helps the next reader.

Set up a development environment
--------------------------------

A contributor install is always an editable clone, so a change to a ``.py``
file takes effect on the next import. Pick the recipe for your platform.

.. tab-set::

   .. tab-item:: pip + venv (Linux, macOS, Windows)
      :sync: dev-pip

      Lightweight, no conda. Python 3.11, 3.12 or 3.13.

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         python3.12 -m venv .venv
         source .venv/bin/activate
         python -m pip install --upgrade pip
         pip install -e ".[dev,test,docs]"
         pre-commit install

      On Windows PowerShell, replace the two venv lines with
      ``py -3.12 -m venv .venv`` and ``.\.venv\Scripts\Activate.ps1``.

   .. tab-item:: conda YAML
      :sync: dev-conda

      Recommended on Windows or for the curated geospatial stack. The env files
      live in the
      `install/ folder <https://github.com/HydroModPy/HydroModPy/tree/main/install>`_.

      .. list-table::
         :header-rows: 1
         :widths: 34 66

         * - Env file
           - Purpose
         * - ``env_hydromodpy.yml``
           - Runtime stack (Spyder included), for running scripts and
             notebooks without editing the source tree.
         * - ``env_hydromodpy_pkg.yml``
           - Editable stack: the same packages plus
             ``pip install -e "..[docs,test]"``.
         * - ``env_hydromodpy_light_pkg.yml``
           - Smaller editable stack, recommended on Linux and WSL for
             command-line development and tests.
         * - ``env_hydromodpy_light.yml``
           - Smaller runtime stack.

      Editable environment, from the repository root (the relative
      ``..[docs,test]`` inside the YAML must reach the project source):

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         conda env create -n hmp-dev -f install/env_hydromodpy_pkg.yml
         conda activate hmp-dev
         pre-commit install

   .. tab-item:: Linux or WSL helper
      :sync: dev-wsl

      Ubuntu and WSL users can bootstrap the editable environment with the
      helper in ``install/``. It installs the system dependencies, creates the
      conda environment and adds the Linux runtime library ``gmsh`` needs.

      .. code-block:: bash

         bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl
         pre-commit install

      Add ``--with-petsc`` to install PETSc, ``petsc4py``, ``mpi4py`` and
      ``mpich`` in the same environment, and ``--full`` for the Spyder and
      Jupyter stack. For day-to-day work, open a ready shell with:

      .. code-block:: bash

         bash install/enter_wsl_dev.sh
         bash install/enter_wsl_dev.sh --headless
         bash install/enter_wsl_dev.sh --output-root /mnt/c/Users/<user>/Documents/HydroModPyOutputs

      If you create the conda environment yourself, add the ``gmsh`` runtime
      shim: ``conda install -n <env> -c conda-forge xorg-libxft``.

After the install, ``hmp`` and ``hydromodpy`` are the same command. Run
``hmp --help`` to list the verbs and ``hmp doctor`` to check the environment.

Extras
~~~~~~

Extras combine in one command, for example ``pip install -e ".[dev,test,docs]"``.
The three a contributor needs every day:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Extra
     - Provides
   * - ``[dev]``
     - ``ruff`` and ``pre-commit``.
   * - ``[test]``
     - ``pytest``, ``pytest-xdist``, ``pytest-timeout``, ``pytest-cov``,
       ``coverage``, ``hypothesis``, ``pyinstrument``, ``pyyaml`` and
       ``jsonschema``.
   * - ``[docs]``
     - Sphinx, the PyData theme, MyST and every extension this site uses,
       plus ``doc8`` and ``sphinx-lint``. The PlantUML jar is not part of it
       (see :doc:`documentation/how-the-docs-are-built`).

Every extra, including ``calibration``, ``mesh``, ``duckdb``, ``mf6api``,
``viz``, ``fair``, ``performance``, ``profiling``, ``metrics``, ``ide`` and
``viewer3d``, is listed with what it installs in
:doc:`architecture/generated/extras`.

Windows with WSL for PETSc
~~~~~~~~~~~~~~~~~~~~~~~~~~

The PETSc-backed Boussinesq backend is Linux only. On a Windows workstation
with WSL, use two environments instead of forcing every dependency into one:
a WSL environment (for example ``hydromodpy-wsl``) for PETSc simulations and
numerical validation tests, and a Windows environment for the Sphinx build.

Run the PETSc smoke suite from PowerShell through WSL:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh"

For the lower-obstacle drying case only:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- python -m pytest tests/validation/numerical/transient/test_boussinesq_drying_petsc.py -q"

Coding style
------------

- Python 3.11 to 3.13. Type hints on every public signature.
- Pydantic v2 only. Every model inherits ``HydroModelBase``, which forbids
  extra keys.
- ``ruff`` is the only linter and formatter. The configuration in
  ``pyproject.toml`` sets a line length of 100.
- A docstring on every public class and function, in the shape described in
  :doc:`docstring-policy`.
- Add a comment only when the reason is not obvious from the code.
- File names are ``snake_case``, class names ``CamelCase``. Common suffixes:
  ``Config``, ``Adapter``, ``Manager``, ``Builder``, ``Resolver``,
  ``Optimizer``, ``Provider``, ``Backend``.
- Reuse the helpers of ``hydromodpy/core/io/`` instead of repeating raster,
  folder or path logic.
- The import layers are a contract: see :doc:`architecture/layered-architecture`.

Hooks
~~~~~

``pre-commit install`` registers the hooks of ``.pre-commit-config.yaml``. On
the staged files they run:

- ``ruff check --fix`` and ``ruff format``;
- ``trailing-whitespace``, ``end-of-file-fixer``, ``check-yaml``,
  ``check-toml`` and ``check-added-large-files`` (1 MB);
- ``gitleaks``, which scans the staged diff for secrets with the engine of
  the CI job;
- ``doc8`` on ``docs/source/**/*.rst``, with a line limit of 130 characters.

If a hook changes a file or refuses a commit, fix the file, stage it again and
commit again.

Run the tests
-------------

Run the tests of the area you touched, and the architecture gate
(``python -m pytest tests/unit/architecture -q``). CI runs the whole suite on
every push. The rules for parallel runs, for the Whitebox tests and for the
scratch folder are in :ref:`run-the-tests`. The tier to pick for a new test is
in :doc:`architecture/how-to/add-a-test`, and what each check of CI means is
in :doc:`project/ci-workflows`.

Build the documentation
-----------------------

.. code-block:: bash

   pip install -e ".[docs]"
   make -C docs html-strict

``html-strict`` is the build CI runs: a warning is an error. The reference
pages are written by the build from the code, so there is nothing to edit for
them. What the build runs and checks, and how to write a page, is in
:doc:`documentation/index`.

Branches, commits and pull requests
-----------------------------------

1. Branch from ``dev`` for normal work, with a short name such as
   ``feat/bdtopage-loader`` or ``docs/release-recipe``. ``main`` is the
   current v2 line, and ``v1.0`` is the frozen v1 line: do not target it.
   Use ``release/X.Y`` only for a stabilisation window and ``maint/1.x`` only
   if v1 maintenance resumes. The tag and branch rules of a release are in
   :doc:`architecture/how-to/cut-a-release`.
2. Group related changes in one focused commit. The subject is a Conventional
   Commits line in the imperative, at most 72 characters including the
   prefix, and no body. A ``commit-msg`` hook can enforce the length and drop
   a body. It lives in ``.git/hooks`` and the repository does not install it
   for you.

   .. code-block:: text

      feat(data): add bdtopage loader
      fix(calibration): resolve structured cells
      docs(contribute): add the release recipe

3. The allowed types are ``feat``, ``fix``, ``refactor``, ``cleanup``,
   ``perf``, ``chore``, ``docs``, ``tests``, ``validation``, ``examples``,
   ``pipeline``, ``config``, ``adapters``, ``data`` and ``style``. The scope
   is the touched area, one lowercase word without underscore:
   ``transport``, ``calibration``, ``boussinesq``, ``modflow6``, ``cli``,
   ``data``, ``docs``. Older commits written as ``[tag] - sentence`` stay as
   they are.
4. The subject names the change and does not explain it. The reason goes in
   the code, in a test, or in ``CHANGELOG.md``.
5. Stage files by name. Do not use ``git add -A`` or ``git add .``.
6. Open the pull request against ``dev``. Reference the issue
   (``Closes #123``) when there is one, and mention a reviewer if the change
   alters modelling outputs, the public API or a user-visible workflow.

By contributing you agree that your contribution is released under the
Eclipse Public License 2.0.

Where to look next
------------------

- :doc:`architecture/mental-model`: how a TOML file becomes a stored run.
- :doc:`architecture/how-to/index`: the recipes.
- :doc:`/reference/parameters/index`: every TOML key, generated from the
  Pydantic models.
- :doc:`/get-started/concepts`: the workspace layout and the TOML inheritance
  rules.
