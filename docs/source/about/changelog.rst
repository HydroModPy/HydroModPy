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
