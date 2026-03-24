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
   python tools/setup_plantuml.py

``python tools/setup_plantuml.py`` downloads a pinned PlantUML jar with SHA256
verification. On Windows it can also install a repo-local Graphviz bundle; on
other platforms it validates the system ``dot`` command unless you pass
``--skip-graphviz``.

Run tests before submitting (if you modify modelling code) and rebuild the docs
to check for warnings:

.. code-block:: bash

   pytest
   python -m tools.doc_gallery --check
   cd docs/readthedocs
   python -m sphinx -E -a -W -b html source _build/html

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
3. If the change affects the illustrated capability gallery, refresh the generated artifacts:

   .. code-block:: bash

      python -m tools.doc_gallery

   This rewrites:

   - ``docs/readthedocs/source/capability_gallery/``
   - ``docs/readthedocs/source/_static/capability_gallery/``
   - according to the manifest in ``tools/doc_gallery/gallery_manifest.py``

   The generator itself is documented in ``tools/doc_gallery/README.md``.
   For future mesh-gallery cases imported from ``C:/results/...``, keep the
   canonical repo tree under ``examples/mesh_gallery/`` and use:

   .. code-block:: bash

      python -m tools.doc_gallery.import_mesh_bundle --help

4. Preview locally with ``sphinx-autobuild -E -a source _build/html``.
5. Run ``python -m tools.doc_gallery --check`` before submitting if you touched
   gallery sources or generated outputs.
6. Keep PlantUML tooling available with ``python tools/setup_plantuml.py`` if
   you work on UML-based architecture pages.
7. Run ``pip install -e '.[docs]'`` after changing the doc extras.

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
