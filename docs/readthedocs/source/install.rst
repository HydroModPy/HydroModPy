Install
=======

Requirements
------------

- Python 3.11 or newer (HydroModPy v0.3.0 dropped support for older versions; see :doc:`news/v0_3_0`).
- Git (only needed if you install from the repository).
- MODFLOW, MODPATH and MT3DMS binaries are included with every installation (PyPI and repository installs).
- The PyHELP binary downloads itself on the first call to the helper module.

Install with pip
----------------

.. tab-set::

   .. tab-item:: PyPI (latest master)

      .. code-block:: bash

         python -m pip install --upgrade pip
         pip install hydromodpy

      This installs the published release from PyPI and exposes the package as
      ``hydromodpy`` in any environment. Need an IDE bundle (Spyder + JupyterLab)?
      install ``hydromodpy[ide]`` instead.

   .. tab-item:: Editable clone

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         python -m pip install --upgrade pip
         pip install -e .

      Editable mode installs the package from the local repository while keeping
      the source tree editable. Ideal for contributions or quick fixes. Install
      the ``[docs]`` extras later only if you work on the documentation.

Full pip packaging is available from v0.3.0 onward. Users pinned to older
releases should rely on the conda environment and the ``v0.2.0`` tag.

Optional extras
---------------

HydroModPy ships several optional extras. Add only what you need. Combine
them inside one ``pip install`` command, for example
``pip install "hydromodpy[ide,viewer3d]"``.

.. list-table::
   :header-rows: 1
   :widths: 18 60

   * - Extra
     - Provides
   * - ``[test]``
     - ``pytest``, ``pytest-xdist``, ``pytest-timeout``, ``coverage`` for
       running the test tiers.
   * - ``[dev]``
     - ``ruff`` and ``pre-commit`` for linting and Git hooks. Required
       only for contributors.
   * - ``[docs]``
     - Sphinx, the RTD theme, ``myst-parser``, ``nbsphinx``, plus the
       extensions used to build this documentation.
   * - ``[ide]``
     - ``ipykernel``, ``jupyterlab``, Spyder, and PySide6.
   * - ``[ugrid]``
     - ``xugrid`` for unstructured mesh handling.
   * - ``[viewer3d]``
     - ``pyvista`` for 3D mesh visualization.

Developer install
-----------------

Contributors should clone the repository, install in editable mode with
the ``[dev,test,docs]`` extras, and register the pre-commit hook:

.. code-block:: bash

   git clone https://github.com/HydroModPy/HydroModPy.git
   cd HydroModPy
   conda create -n hmp-dev python=3.12 -y
   conda activate hmp-dev
   pip install -e ".[dev,test,docs]"
   pre-commit install

The ``pre-commit install`` step registers the Git hook that runs ``ruff``
before each commit. See :doc:`contribute` for the full contributor
workflow (issue filing, coding style, test tiers, doc build, pull request
conventions).

Install with conda
------------------

Three ready-to-use environment files live in ``install/``. Pick the tabbed recipe
that matches your workflow.

.. tab-set::

   .. tab-item:: Conda (Runtime stack)

      Installs the runtime stack (Spyder included) for executing scripts and
      notebooks without touching the local source tree.

      .. code-block:: bash

         conda env create -n <env> -f install/env_hydromodpy.yml
         conda activate <env>

      When running scripts or notebooks inside this repository, append the
      project root to ``sys.path`` so the runtime-only environment sees the
      package:

      .. code-block:: python

         # ROOT DIRECTORY
         import sys
         sys.path.append(r"/absolute/path/to/your/HydroModPy")

      Pip-based installs expose ``hydromodpy`` globally, so the snippet is not
      required outside this workflow.

   .. tab-item:: Conda (Editable stack)

      Sets up the same environment but finishes with ``pip install -e ..`` so
      the cloned repository stays importable everywhere.

      .. code-block:: bash

         conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml
         conda activate <env>-pkg

      Run the commands from the repository root (``install/`` sits at the top
      level) so the relative ``pip install -e ..`` executed by the YAML file can
      reach the project.

   .. tab-item:: Conda (Light editable stack)

      Uses a smaller editable stack intended for Linux/WSL command-line
      development and test execution without the Spyder bundle.

      .. code-block:: bash

         conda env create -n <env>-light -f install/env_hydromodpy_light_pkg.yml
         conda activate <env>-light

      As with the other editable recipe, run the command from the repository
      root so the relative ``pip install -e ..`` in the YAML file resolves back
      to ``HydroModPy/``.

Command recipes
---------------

Pick the setup that matches your workflow. Replace ``<env>`` with your
environment name, set ``<py>`` to the desired Python version (3.11-3.13), and switch
``hydromodpy`` to ``"hydromodpy[docs]"`` if you need the documentation extras.

.. dropdown:: Conda + YAML
   :color: secondary

   Ready-made Conda environments. Replace ``<env>`` with your environment name.

   .. code-block:: bash

      # Clone + runtime stack (scripts, notebooks)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Already cloned: create/activate the runtime env
      conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Clone + editable stack (adds pip install -e ..)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

   .. code-block:: bash

      # Already cloned: create/activate the editable env
      conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

   .. code-block:: bash

      # Clone + light editable stack (recommended on Linux/WSL)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && conda env create -n <env>-light -f install/env_hydromodpy_light_pkg.yml && conda activate <env>-light

   .. code-block:: bash

      # Already cloned: create/activate the light editable env
      conda env create -n <env>-light -f install/env_hydromodpy_light_pkg.yml && conda activate <env>-light

.. dropdown:: Conda + PyPI
   :color: secondary

   Create a fresh Conda (or Mamba) env and install HydroModPy directly from
   PyPI, so you do not need to download the codebase.

   .. code-block:: bash

      # Without cloning
      conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install --upgrade hydromodpy

   .. code-block:: bash

      # Without cloning, editable mode
      conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install -e .

   .. code-block:: bash

      # Clone first (optional), then install from PyPI
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install --upgrade hydromodpy

   .. code-block:: bash

      # Clone first, then install in editable mode (pip install -e .)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install -e .

   Add ``"hydromodpy[ide]"`` at the end if you want Spyder and JupyterLab bundled.

.. dropdown:: venv + PyPI
   :color: secondary

   Rely only on the standard ``venv`` module. This keeps everything on pip, but
   you must have the system libraries required by GDAL/Proj.

   .. rubric:: Linux / macOS

   .. code-block:: bash

      python<py> -m venv <env> && source <env>/bin/activate && python -m pip install --upgrade pip && pip install --upgrade hydromodpy

   .. rubric:: Windows (PowerShell)

   .. code-block:: powershell

      py -<py> -m venv <env> ; .\<env>\Scripts\Activate.ps1 ; python -m pip install --upgrade pip ; pip install --upgrade hydromodpy

   .. rubric:: Windows (CMD)

   .. code-block:: batch

      py -<py> -m venv <env> && call <env>\Scripts\activate.bat && python -m pip install --upgrade pip && pip install --upgrade hydromodpy

   Append ``"hydromodpy[ide]"`` to either command if you want the IDE extras.

Linux / WSL quick start
-----------------------

Ubuntu and WSL users can bootstrap the editable development environment with
the helper script shipped in ``install/``. It installs the minimal system
dependency, creates the Conda env, and adds the Linux runtime library needed by
``gmsh``:

.. code-block:: bash

   bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl

Add ``--with-petsc`` to install PETSc, ``petsc4py``, ``mpi4py``, and ``mpich``
inside the same environment:

.. code-block:: bash

   bash install/setup_wsl_dev.sh --env-name hydromodpy-wsl --with-petsc

For day-to-day work after the environment already exists, open one ready shell
with the companion helper:

.. code-block:: bash

   bash install/enter_wsl_dev.sh

The helper sources Conda, activates the chosen env, and moves to the repository
root. Add ``--headless`` for non-interactive runs or ``--output-root`` to send
outputs directly to one Windows path:

.. code-block:: bash

   bash install/enter_wsl_dev.sh --headless
   bash install/enter_wsl_dev.sh --output-root /mnt/c/Users/<user>/Documents/HydroModPyOutputs

If Conda is not installed inside WSL yet, Miniforge is a compact default:

.. code-block:: bash

   sudo apt update && sudo apt install -y curl git libglu1-mesa
   curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
   bash Miniforge3-Linux-x86_64.sh
   source ~/miniforge3/etc/profile.d/conda.sh

If you create the Conda environment manually instead of using
``install/setup_wsl_dev.sh``, add the Linux ``gmsh`` runtime shim yourself:

.. code-block:: bash

   conda install -n <env>-light -c conda-forge xorg-libxft

After activation, a typical Linux/WSL non-interactive test session is:

.. code-block:: bash

   export MPLBACKEND=Agg
   python -m pytest tests/unit -q
   hmp test regression --fast -j 2
   hmp test validation --fast

Upgrade
-------

.. code-block:: bash

   pip install --upgrade hydromodpy

Editable installs can be updated with ``git pull`` followed by the same command.

Check the installation
----------------------

.. code-block:: python

   import hydromodpy
   from hydromodpy.core.config import HydroModPyConfig
   from hydromodpy.spatial.geographic import CatchmentDelineation
   # Examples of submodule imports
   from hydromodpy.display import get, list_figures
   from hydromodpy.core.tools.display import plot_params

   font_sizes = plot_params(8, 15, 18, 20)  # small, medium, intermediate, large
   print([spec.name for spec in list_figures()[:3]])
   print(hydromodpy.__version__)

Refer to :doc:`getting_started/index` for a guided first workflow once the
import works. Use :doc:`examples` when you want the full notebook and script
inventory.

Spyder note
-----------

``spyder-kernels`` ships with HydroModPy so Spyder can attach to any prepared
environment. Install the IDE itself via the Conda YAML files (Spyder is already
included) or by adding the ``ide`` extra ::

   pip install "hydromodpy[ide]"

Manual install remains possible with ``conda install spyder``.

Python 3.8 users
----------------

If you must stay on Python 3.8.10, stick to release ``v0.2.0`` by cloning
https://github.com/HydroModPy/HydroModPy/releases/tag/v0.2.0 and following the
conda recipe above. Later versions require Python 3.11+ and will not install on
older interpreters.

.. dropdown:: Compatibility note
   :color: info
   :icon: info

   Known ``pyproj`` / ``proj.db`` issues observed in earlier releases were fixed
   from v0.3.0 onward. Upgrade to this version (or newer) to avoid the missing
   database errors that appeared on some conda setups.
