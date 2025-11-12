Install
=======

Requirements
------------

- Python 3.11 or newer (HydroModPy v0.3.0 dropped support for older versions; see :doc:`news/v0_3_0`).
- Git (only needed if you install from the repository).
- MODFLOW/MODPATH binaries are downloaded automatically on first import.
- MT3DMS binaries ship with every install (PyPI or Git).
- The PyHELP binary downloads itself on the first call to the helper module.

Install with pip
----------------

.. tab-set::

   .. tab-item:: PyPI (latest master)

      .. code-block:: bash

         python -m pip install --upgrade pip
         pip install hydromodpy

      This installs the published release from PyPI and exposes the package as
      ``hydromodpy`` in any environment.

   .. tab-item:: Test PyPI (development)

      .. code-block:: bash

         python -m pip install --upgrade pip
         pip install -i https://test.pypi.org/simple/ hydromodpy

      Use this channel to preview the dev branch before it lands on PyPI. Expect
      breaking changes (see :doc:`news/v0_3_0`).

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

Use the environment recipe provided in ``install/env_hydromodpy.yml``.

.. code-block:: bash

   git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
   cd HydroModPy
   conda env create -f install/env_hydromodpy.yml -n hydromodpy
   conda activate hydromodpy

When running scripts/notebooks inside this cloned repository, add the project
root to ``sys.path`` so Python can resolve local modules:

.. code-block:: python

   # ROOT DIRECTORY
   import sys
   sys.path.append(r"/absolute/path/to/your/HydroModPy")

This snippet is not required for pip installations because the package is
installed system-wide.

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

The default extras install ``spyder-kernels``, so Spyder can connect to the
environment out of the box. You still need to install the Spyder IDE itself via
``conda install spyder`` or ``pip install spyder`` if you plan to use it.

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
