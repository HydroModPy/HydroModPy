Install
=======

.. warning::

   You are reading the HydroModPy **v1.0** documentation, the version described in
   the HESS technical note
   (`preprint <https://doi.org/10.5194/egusphere-2026-868>`_). The ``v1.0`` branch
   is the reference cited by the paper and still receives fixes. For the latest
   development version, see HydroModPy v2 on ``main``:
   https://hydromodpy.github.io/main/

Requirements
------------

- Python 3.11 or newer (HydroModPy v0.3.0 dropped support for older versions;
  see :doc:`news/v0_3_0`).
- Git (only needed if you install from the repository).
- MODFLOW, MODPATH and MT3DMS binaries are included with every installation
  (PyPI and repository installs).
- The PyHELP binary downloads itself on the first call to the helper module.

Install with pip
----------------

.. tab-set::

   .. tab-item:: PyPI (v1.0)

      .. code-block:: bash

         python -m pip install --upgrade pip
         pip install "hydromodpy==1.0.*"

      This installs the published release from PyPI and exposes the package as
      ``hydromodpy`` in any environment. Need an IDE bundle (Spyder + JupyterLab)?
      install ``hydromodpy[ide]==1.0.*`` instead.

      The ``==1.0.*`` specifier always resolves to the latest ``1.0.X`` patch
      and never crosses over to the v2 series. ``==1.0.0`` pins one exact
      release, and a bare ``pip install hydromodpy`` follows the newest
      release of any series.

   .. tab-item:: Editable clone

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         git checkout v1.0
         python -m pip install --upgrade pip
         pip install -e .

      Editable mode installs the package from the local repository while keeping
      the source tree editable. Use the v2 documentation for active
      contributions. Install the ``[docs]`` extras later only if you work on the
      v1.0 documentation.

Full pip packaging is available from v0.3.0 onward. Users pinned to older
releases should rely on the conda environment and the ``v0.2.0`` tag.

Install with conda
------------------

Two ready-to-use environment files live in ``install/``. Pick the tabbed recipe
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

Command recipes
---------------

Pick the setup that matches your workflow. Replace ``<env>`` with your
environment name and set ``<py>`` to the desired Python version (3.11–3.13).
Use ``"hydromodpy[docs]==1.0.*"`` if you need the documentation extras.

.. dropdown:: Conda + YAML
   :color: secondary

   Ready-made Conda environments. Replace ``<env>`` with your environment name.

   .. code-block:: bash

      # Clone + runtime stack (scripts, notebooks)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && git checkout v1.0 && conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Already cloned: create/activate the runtime env
      conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Clone + editable stack (adds pip install -e ..)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && git checkout v1.0 && conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

   .. code-block:: bash

      # Already cloned: create/activate the editable env
      conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

.. dropdown:: Conda + PyPI
   :color: secondary

   Create a fresh Conda (or Mamba) env and install HydroModPy directly from
   PyPI, so you do not need to download the codebase.

   .. code-block:: bash

      # Without cloning
      conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install "hydromodpy==1.0.*"

   .. code-block:: bash

      # Without cloning, editable mode
      conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install -e .

   .. code-block:: bash

      # Clone first (optional), then install from PyPI
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && git checkout v1.0 && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install "hydromodpy==1.0.*"

   .. code-block:: bash

      # Clone first, then install in editable mode (pip install -e .)
      git clone https://github.com/HydroModPy/HydroModPy.git && cd HydroModPy && git checkout v1.0 && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install -e .

   Add ``"hydromodpy[ide]==1.0.*"`` at the end if you want Spyder and
   JupyterLab bundled.

.. dropdown:: venv + PyPI
   :color: secondary

   Rely only on the standard ``venv`` module. This keeps everything on pip, but
   you must have the system libraries required by GDAL/Proj.

   .. rubric:: Linux / macOS

   .. code-block:: bash

      python<py> -m venv <env> && source <env>/bin/activate && python -m pip install --upgrade pip && pip install "hydromodpy==1.0.*"

   .. rubric:: Windows (PowerShell)

   .. code-block:: powershell

      py -<py> -m venv <env> ; .\<env>\Scripts\Activate.ps1 ; python -m pip install --upgrade pip ; pip install "hydromodpy==1.0.*"

   .. rubric:: Windows (CMD)

   .. code-block:: batch

      py -<py> -m venv <env> && call <env>\Scripts\activate.bat && python -m pip install --upgrade pip && pip install "hydromodpy==1.0.*"

   Append ``"hydromodpy[ide]==1.0.*"`` to either command if you want the IDE
   extras.

Track v1.0
----------

.. code-block:: bash

   pip install "hydromodpy==1.0.*"

This is the recommended specifier for anyone reproducing the paper results.
It picks up every ``1.0.X`` bug fix published on PyPI and never upgrades to
the v2 series, which has a different interface.

Editable installs should track the ``v1.0`` branch, which stays current with
fixes for the published release.

Check the installation
----------------------

.. code-block:: python

   import hydromodpy
   from hydromodpy import watershed_root
   # Examples of submodule imports
   from hydromodpy.display import visualization_watershed, visualization_results
   from hydromodpy.tools import toolbox

   font_sizes = toolbox.plot_params(8, 15, 18, 20)  # small, medium, intermediate, large
   print(hydromodpy.__version__)

Refer to :doc:`examples` for complete notebooks and scripts once the import
works.

Spyder note
-----------

``spyder-kernels`` ships with HydroModPy so Spyder can attach to any prepared
environment. Install the IDE itself via the Conda YAML files (Spyder is already
included) or by adding the ``ide`` extra ::

   pip install "hydromodpy[ide]==1.0.*"

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
   from v0.3.0 onward. Use v1.0.0 to avoid the missing database errors that
   appeared on some conda setups.
