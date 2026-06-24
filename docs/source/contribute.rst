Contribute
==========

.. warning::

   You are reading the HydroModPy **v1.0** documentation, the version described in
   the HESS technical note
   (`preprint <https://doi.org/10.5194/egusphere-2026-868>`_). The ``v1.0`` branch
   is the reference cited by the paper and still receives fixes. For the latest
   development version, see HydroModPy v2 on ``main``:
   https://hydromodpy.github.io/main/

The ``v1.0`` branch stays available as the citable reference for the paper and
accepts bug fixes and documentation updates. New features and active development
happen on the v2 codebase on ``main``. Pick your target accordingly:

- **Bug fix or doc update for the published v1.0** -- branch from ``v1.0`` and open a
  pull request against ``v1.0``.
- **New feature or larger change** -- work on the v2 codebase on ``main``.

Set up the environment
----------------------

.. code-block:: bash

   git clone https://github.com/HydroModPy/HydroModPy.git
   cd HydroModPy
   git checkout v1.0
   pip install -e '.[docs]'

Run the tests before submitting (if you modify modelling code) and rebuild the
docs to check for warnings:

.. code-block:: bash

   pytest
   make -C docs html

Coding guidelines
-----------------

- Target Python 3.11+ and keep type hints where practical.
- Prefer ``toolbox`` helpers over duplicating raster or folder logic.
- Add docstrings for public methods/classes and keep parameter names consistent
  with existing modules.

Documentation workflow
----------------------

1. Update the relevant ``.rst`` pages plus the notebooks or scripts you touched.
2. Preview locally with ``make -C docs html`` (built from ``docs/source``).
3. Run ``pip install -e '.[docs]'`` after changing the doc extras.

The ``v1.0`` documentation is published automatically to
https://hydromodpy.github.io/v1.0/ when the ``v1.0`` branch is updated.

Submitting changes
------------------

1. Ensure ``git status`` contains only the files related to your change.
2. Push your branch to GitHub and open a pull request against ``v1.0`` (fixes) or
   ``main`` (new development).
3. Mention reviewers if the change affects modelling outputs or user-visible
   workflows.
