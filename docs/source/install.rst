:html_theme.sidebar_secondary.remove:

Install
=======

.. raw:: html

   <p class="lead">
   Install HydroModPy with the package manager you already use. Pick a
   tab, run the command, you are ready to go.
   </p>

.. admonition:: Want to contribute, build the docs, or run the test suite?
   :class: tip

   This page covers the user install. For the editable clone, the
   pre-commit hooks, the Sphinx toolchain, or the WSL/PETSc developer
   environment, head over to the :doc:`contributor install <contribute>`
   in the developer section.

Quick install
-------------

.. code-block:: bash

   pip install --pre hydromodpy

This documentation targets the v2 alpha line. The ``--pre`` flag is needed
while v2 is published as ``2.0.0aN``, ``2.0.0bN``, or ``2.0.0rcN``.
Without ``--pre``, ``pip install hydromodpy`` installs the latest stable
release from PyPI. The two CLI entry points become available straight away:

.. code-block:: bash

   hmp --version
   hmp --help

Need an IDE bundle (Spyder + JupyterLab)? Use ``pip install --pre
"hydromodpy[ide]"`` instead. The full list of optional extras is
:ref:`below <install-extras>`.
The default install includes the ``optuna`` calibration sampler used by
the Nancon calibration example.

Choose your installer
---------------------

.. tab-set::

   .. tab-item:: pip + venv
      :sync: pip

      The lightest path. Works on any supported Python interpreter
      (3.11, 3.12, or 3.13).

      .. code-block:: bash

         python3.12 -m venv .venv
         source .venv/bin/activate
         python -m pip install --upgrade pip
         pip install --pre hydromodpy

      On Windows PowerShell, replace the first two lines with
      ``py -3.12 -m venv .venv`` and ``.\.venv\Scripts\Activate.ps1``.

   .. tab-item:: uv
      :sync: uv

      `uv <https://docs.astral.sh/uv/>`_ is a fast, drop-in replacement
      for ``pip``. Recommended when bootstrapping a fresh environment
      or a CI job.

      .. code-block:: bash

         uv venv .venv --python 3.12
         source .venv/bin/activate
         uv pip install --pre hydromodpy

      One-shot run without a long-lived venv:

      .. code-block:: bash

         uvx --from hydromodpy hmp --help

   .. tab-item:: conda
      :sync: conda

      Recommended when geospatial libraries are tricky to build from
      source (Windows, restricted environments). A minimal env is
      enough:

      .. code-block:: bash

         conda create -n hmp python=3.12 pip
         conda activate hmp
         pip install --pre hydromodpy

      For the curated environment YAMLs (runtime stack, with Spyder
      and the geospatial dependencies), download the file you need
      from the `install/ folder on GitHub
      <https://github.com/HydroModPy/HydroModPy/tree/main/install>`_,
      then create the env from the downloaded copy:

      .. code-block:: bash

         conda env create -n hmp -f env_hydromodpy.yml
         conda activate hmp

   .. tab-item:: docker
      :sync: docker

      Truly zero local install: only Docker (or Podman) is required on
      the host. No clone, no Python, no pip.

      **Pull from the registry (recommended):**

      .. code-block:: bash

         docker run --rm ghcr.io/hydromodpy/hydromodpy --help

      .. admonition:: Hosted image: coming soon
         :class: note

         The official ``hydromodpy`` image will be published on the
         `GitHub Container Registry
         <https://github.com/HydroModPy/HydroModPy/pkgs/container/hydromodpy>`_
         at ``ghcr.io/hydromodpy/hydromodpy`` once the publish step
         is enabled in the CI. Until then, use the local build below.

      **Local build (works today):**

      .. code-block:: bash

         git clone https://github.com/HydroModPy/HydroModPy.git
         cd HydroModPy
         docker build -t hydromodpy .
         docker run --rm hydromodpy --help

      Solver binaries are not embedded in the image. They are pulled
      into the container on the first solver run, into the cache
      under the ``hmp`` user home.

   .. tab-item:: conda-forge
      :sync: conda-forge

      .. admonition:: Coming soon
         :class: note

         A ``hydromodpy`` feedstock on conda-forge is being prepared.
         In the meantime, use the **conda** tab above with
         ``env_hydromodpy.yml`` from the
         `install/ folder on GitHub
         <https://github.com/HydroModPy/HydroModPy/tree/main/install>`_,
         or fall back to ``pip`` inside a conda env.

.. _install-extras:

Optional extras
---------------

HydroModPy ships a few optional extras. Add only what you need; combine
them inside one ``pip install`` command, for example
``pip install "hydromodpy[ide,viewer3d]"``.

.. list-table::
   :header-rows: 1
   :widths: 18 60

   * - Extra
     - Provides
   * - ``[ide]``
     - ``ipykernel``, ``jupyterlab``, Spyder, and PySide6.
   * - ``[viewer3d]``
     - ``pyvista`` for 3D mesh visualization.
   * - ``[calibration]``
     - ``cma`` and ``cmaes`` for CMA-ES calibration variants. The
       default ``optuna`` TPE sampler is installed by the base package.
   * - ``[test]``
     - ``pytest``, ``pytest-xdist``, ``pytest-timeout``, ``coverage``
       for running the test tiers.
   * - ``[dev]``
     - ``ruff`` and ``pre-commit`` for linting and Git hooks.
       Contributor-only.
   * - ``[docs]``
     - Sphinx, the PyData theme, ``myst-parser``, ``nbsphinx``, plus
       the extensions used to build this documentation.
       Contributor-only.

The ``[dev]`` and ``[docs]`` extras belong to the contributor flow.
See :doc:`contribute` for the editable clone and the full developer
setup.

Verify the install
------------------

Once installed, this short snippet imports the public surface and
prints the version:

.. code-block:: python

   import hydromodpy
   from hydromodpy.config import HydroModPyConfig
   from hydromodpy.display import list_figures

   print("hydromodpy", hydromodpy.__version__)
   print("first 3 figures:", [spec.name for spec in list_figures()[:3]])

If the imports succeed, you are ready to follow
:doc:`getting_started/index` for the first guided run, or
:doc:`user_guide/cookbook/index` for short TOML-first recipes.

Upgrade
-------

.. code-block:: bash

   pip install --upgrade hydromodpy

The same command works inside a uv-managed venv, a conda env, or any
other PEP 668 compliant environment.

Where next
----------

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card:: First run
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: getting_started/index
      :link-type: doc

      Concepts in five minutes, then a guided end-to-end project on a
      real basin.

   .. grid-item-card:: Cookbook
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/cookbook/index
      :link-type: doc

      Short TOML-first recipes for the most common HydroModPy tasks.

   .. grid-item-card:: Contribute
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: contribute
      :link-type: doc

      Editable clone, pre-commit hooks, ``[dev,test,docs]`` extras,
      WSL/PETSc helpers, and the documentation toolchain.

Solver binaries
---------------

MODFLOW, MODPATH, and MT3D-USGS executables are downloaded on demand
the first time a solver runs, into ``~/.cache/hydromodpy/bin/`` (or
the platform equivalent). Override the location with the
``HMP_BIN`` environment variable.

In most cases nothing is required from the user: the first solver run
populates the cache transparently. The dropdown below covers the
explicit commands and the air-gapped flow.

.. dropdown:: Eager fetch, custom location, and air-gapped setups
   :icon: package
   :color: secondary

   Use the explicit command if you need to control when binaries
   arrive on disk:

   .. code-block:: bash

      hmp install-binaries                      # fetch everything now
      hmp install-binaries --subset mf6,mfnwt   # restrict to a subset
      hmp install-binaries --mf6-prt            # fetch mf6 for MODFLOW 6 PRT
      hmp install-binaries --bindir <dir>       # fetch into a custom directory
      hmp install-binaries --upgrade            # force re-download
      hmp install-binaries --release <tag>      # pin a specific release tag

   MF6-PRT does not install a separate ``prt`` program. The Particle
   Tracking model is built into recent ``mf6`` executables, so
   ``--mf6-prt`` is a readable shortcut for installing ``mf6`` only. If
   an older ``mf6`` is already cached, combine it with ``--upgrade``.

   Binaries are pulled from the ``MODFLOW-ORG/executables`` GitHub
   release. The release tag is pinned by the installed HydroModPy
   version; integrity is provided by GitHub TLS plus the release-tag
   pin, which is also the recommended reproducibility lever. Use
   ``hmp install-binaries --help`` to see the tag baked into your
   install.

   Cache layout:

   .. code-block:: text

      ~/.cache/hydromodpy/bin/
      ├── mf6
      ├── mfnwt
      ├── mp6
      ├── mp7
      ├── mt3dusgs
      └── .manifest.json

   The ``.manifest.json`` file records the release tag and the
   download timestamp written on first fetch.

   When ``HMP_BIN`` (or ``--bindir``) points at a user-managed
   directory, HydroModPy never writes into it: missing binaries
   surface at solver execution time with a clear ``FileNotFoundError``.
   For air-gapped or CI deployments, run ``hmp install-binaries`` once
   during provisioning so subsequent runs are deterministic and
   offline-safe.

   The PyHELP binary follows the same lazy pattern and downloads
   itself on the first call to the helper module.

.. dropdown:: Compatibility notes
   :icon: info
   :color: info

   - **Python version.** Releases require Python 3.11 or newer. If you
     must stay on an older interpreter, install an earlier HydroModPy
     release from the
     `release archive <https://github.com/HydroModPy/HydroModPy/releases>`_
     and follow the install recipe shipped with that tag.
   - **pyproj / proj.db.** Errors observed on some early conda setups
     have been fixed in current releases. Always run the latest
     version when possible.
