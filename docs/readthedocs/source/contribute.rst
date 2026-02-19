Contribute
==========

HydroModPy welcomes contributions for bug fixes, new workflows, documentation,
and example notebooks. This page summarises the expected workflow.

Set up the environment
----------------------

.. code-block:: bash

   git clone https://github.com/HydroModPy/HydroModPy.git
   cd HydroModPy
   pip install -e '.[docs]'

Run tests before submitting (if you modify modelling code) and rebuild the docs
to check for warnings:

.. code-block:: bash

   pytest
   cd docs/readthedocs
   sphinx-build -b html source _build/html

Coding guidelines
-----------------

- Target Python 3.11+ and keep type hints where practical.
- Prefer ``toolbox`` helpers over duplicating raster or folder logic.
- Add docstrings for public methods/classes and keep parameter names consistent
  with existing modules.

Documentation workflow
----------------------

1. Work in a feature branch derived from ``dev``.
2. Update the relevant ``.rst`` pages plus the notebooks or scripts you touched.
3. Preview locally with ``sphinx-autobuild -E -a source _build/html``.
4. Run ``pip install -e '.[docs]'`` after changing the doc extras.

Submitting changes
------------------

1. Ensure ``git status`` contains only the files related to your change.
2. Push the branch to GitHub and open a pull request against ``dev``.
3. Mention reviewers if the change affects modelling outputs or user-visible
   workflows.

Releases
--------

Stable releases advance from ``dev`` to ``latest`` once:

- Notebooks run without warnings.
- The changelog and :doc:`news` page mention the key updates.
- Tags are created (``git tag v0.3.0``) and pushed (``git push --tags``).
