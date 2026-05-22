Contribute
==========

.. warning::

   This documentation describes the archived HydroModPy v1.0.0 release. The
   ``archive-v1`` branch is no longer maintained day to day. Existing projects
   may stay pinned to the ``v1.0.0`` tag. New development should move to
   HydroModPy v2 on ``main``:
   https://hydromodpy-docs.readthedocs.io/en/main/

HydroModPy v1 is archived. Active pull requests for bug fixes, new workflows,
documentation, and example notebooks should target the v2 codebase on ``main``.
This page records the historical v1 workflow for archive users.

Set up the environment
----------------------

.. code-block:: bash

   git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git
   cd HydroModPy
   git checkout v1.0.0
   pip install -e '.[docs]'

Run tests before submitting (if you modify modelling code) and rebuild the docs
to check for warnings:

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

1. Work in a feature branch derived from ``main`` for active v2 development.
2. Update the relevant ``.rst`` pages plus the notebooks or scripts you
   touched.
3. Preview locally with ``make -C docs html``.
4. Run ``pip install -e '.[docs]'`` after changing the doc extras.

Submitting changes
------------------

1. Ensure ``git status`` contains only the files related to your change.
2. Push the branch to GitLab and open a merge request against ``main``.
3. Mention reviewers if the change affects modelling outputs or user-visible
   workflows.

Versioning policy
-----------------

- ``archive-v1`` is the frozen v1.0.0 archive branch.
- ``maint/1.x`` is reserved for a future v1 maintenance branch, only if active
  v1 maintenance resumes.
- Do not use ``v1`` or ``v2`` as long-lived branch names.

Releases
--------

Stable v2 releases advance from ``main`` once:

- Notebooks run without warnings.
- The changelog and :doc:`news` page mention the key updates.
- Tags are created and pushed.
