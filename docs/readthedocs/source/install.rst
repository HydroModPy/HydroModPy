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

         git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
         cd HydroModPy
         python -m pip install --upgrade pip
         pip install -e .

      Editable mode installs the package from the local repository while keeping
      the source tree editable. Ideal for contributions or quick fixes. Install
      the ``[docs]`` extras later only if you work on the documentation.

Full pip packaging is available from v0.3.0 onward. Users pinned to older
releases should rely on the conda environment and the ``v0.2.0`` tag.

Install with conda
------------------

Two ready-to-use environment files live in ``install/``:

- ``env_hydromodpy.yml`` installs the runtime stack (Spyder included) for running
  scripts and notebooks.
- ``env_hydromodpy_pkg.yml`` installs the same stack then runs ``pip install -e ..``
  so the local repository is importable everywhere.

When running scripts/notebooks inside this cloned repository, add the project
root to ``sys.path`` if you rely on the runtime-only YAML file:

.. code-block:: python

   # ROOT DIRECTORY
   import sys
   sys.path.append(r"/absolute/path/to/your/HydroModPy")

This snippet is not required for pip installations because the package is
installed system-wide.

Command recipes
---------------

Pick the setup that matches your workflow. Replace ``<env>`` with your
environment name, set ``<py>`` to the desired Python version (3.11–3.13), and switch
``hydromodpy`` to ``"hydromodpy[docs]"`` if you need the documentation extras.

.. dropdown:: Conda + YAML
   :color: secondary

   Ready-made Conda environments. Replace ``<env>`` with your environment name.

   .. code-block:: bash

      # Clone + runtime stack (scripts, notebooks)
      git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git && cd HydroModPy && conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Already cloned: create/activate the runtime env
      conda env create -n <env> -f install/env_hydromodpy.yml && conda activate <env>

   .. code-block:: bash

      # Clone + editable stack (adds pip install -e ..)
      git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git && cd HydroModPy && conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

   .. code-block:: bash

      # Already cloned: create/activate the editable env
      conda env create -n <env>-pkg -f install/env_hydromodpy_pkg.yml && conda activate <env>-pkg

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
      git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git && cd HydroModPy && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install --upgrade hydromodpy

   .. code-block:: bash

      # Clone first, then install in editable mode (pip install -e .)
      git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git && cd HydroModPy && conda create -y -n <env> python=<py> pip && conda activate <env> && python -m pip install --upgrade pip && pip install -e .

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

Upgrade
-------

.. code-block:: bash

   pip install --upgrade hydromodpy

Editable installs can be updated with ``git pull`` followed by the same command.

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

   pip install "hydromodpy[ide]"

Manual install remains possible with ``conda install spyder``.

Python 3.8 users
----------------

If you must stay on Python 3.8.10, stick to release ``v0.2.0`` by cloning
https://gitlab.com/Alex-Gauvain/HydroModPy/-/releases/v0.2.0 and following the
conda recipe above. Later versions require Python 3.11+ and will not install on
older interpreters.

.. dropdown:: Compatibility note
   :color: info
   :icon: info

   Known ``pyproj`` / ``proj.db`` issues observed in earlier releases were fixed
   from v0.3.0 onward. Upgrade to this version (or newer) to avoid the missing
   database errors that appeared on some conda setups.
