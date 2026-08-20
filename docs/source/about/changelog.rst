Changelog
=========

The canonical changelog lives in ``CHANGELOG.md`` at the repository
root. It follows the
`Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_ convention
and the project adheres to
`Semantic Versioning <https://semver.org/>`_.

For the full history with every entry, see the file on GitHub:
`CHANGELOG.md
<https://github.com/HydroModPy/HydroModPy/blob/main/CHANGELOG.md>`_.

Current lines
-------------

Two lines exist side by side. ``v1.0.0`` is the last published v1 release
and it is frozen on its own ``v1.0`` branch. ``main`` carries the v2 line
at version ``2.0.0a1``. That pre-release is not tagged yet, so ``v1.0.0``
is still the most recent tag. See :doc:`release_policy` for the branch
and tag rules.

Recent releases
---------------

The most recent stable releases at the time of writing.

.. dropdown:: v0.3.3 - 2025-12-03
   :open:

   - Lightweight conda environment option (``env_hydromodpy_light_pkg.yml``)
     for Linux/WSL command-line development without the Spyder bundle.
   - Surface routing consolidated under ``masstransfer``.
   - Leaner SIM2 memory use during retrieval.

.. dropdown:: v0.3.2 - 2025-11-28

   - SIM2 retrieval reworked with coarse clip then reproject (memory and
     time gains).
   - ``disk_clip`` accepts ``.shp``, ``.gpkg``, and ``.geojson``.

.. dropdown:: v0.3.1 - 2025-11-14

   - Installation guide reorganized.
   - Dual YAML options for runtime versus editable installs.
   - NumPy >= 2 baseline.

.. dropdown:: v0.3.0

   First version with full pip packaging. Earlier releases (``v0.2.0``
   and below) require the conda recipe.

How releases are tagged
-----------------------

Each release receives a Git tag and, for stable releases, a Zenodo DOI.
The reproducibility lockfile ``hydromodpy.lock`` records the package
version, solver binary release tag and input fingerprints when that
evidence is available. Frozen replay requires it; normal runs may only
emit a reproducibility warning when cache metadata is missing.

See also
--------

- :doc:`../how_to_cite` for citation entries.
- :doc:`roadmap` for the planned development phases.
