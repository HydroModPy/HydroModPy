Changelog
=========

The canonical changelog lives in ``CHANGELOG.md`` at the repository
root. It follows the
`Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_ convention
and the project adheres to
`Semantic Versioning <https://semver.org/>`_.

For the full history with every entry, see the file on GitHub:
`CHANGELOG.md
<https://github.com/HydroModPy/HydroModPy/blob/master/CHANGELOG.md>`_.

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
The reproducibility lockfile ``hydromodpy.lock`` written next to every
run records the exact package version and the solver binary release
tag, so a published result can be reproduced from the same TOML config
without reading this changelog.

See also
--------

- :doc:`../how_to_cite` for citation entries.
- :doc:`roadmap` for the planned development phases.
