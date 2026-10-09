Cut a release
=============

A release is a Git tag. The tag starts three jobs: the publication to PyPI, the
GitHub Release, and the build of the documentation for that version. This page
is the maintainer's checklist. What a version number means for a user is in the
release policy of the About door.

Version and tag syntax
----------------------

Versions follow Semantic Versioning for meaning and PEP 440 for the string.

.. code-block:: text

   MAJOR.MINOR.PATCH          2.0.0
   MAJOR.MINOR.PATCHaN        2.0.0a1     alpha
   MAJOR.MINOR.PATCHbN        2.0.0b1     beta
   MAJOR.MINOR.PATCHrcN       2.0.0rc1    release candidate

The Git tag is the version with a leading ``v``: ``v2.0.0a5``, ``v2.0.0``. Do not
invent other forms such as ``release-v2`` or ``v2-beta``.

- ``MAJOR`` is an incompatible change of the public contract: a removed or
  renamed public function, command, config field or storage format, or a solver
  behaviour that makes users edit their files.
- ``MINOR`` is a compatible addition: a solver, an optional field with a default,
  a command.
- ``PATCH`` is a compatible bug fix and nothing else.

HydroModPy keeps no compatibility shim for a removed public name. A change that
makes users edit their code, TOML or project layout is a ``MAJOR`` change, unless
it lands before a stable release, in an ``a``, ``b`` or ``rc`` pre-release.

Four places must agree
----------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Where
     - What
   * - ``pyproject.toml``
     - ``[project] version``. This is the source of the package version, and a
       source checkout reads its ``__version__`` from it.
   * - ``hydromodpy/core/version.py``
     - ``_FALLBACK_VERSION``, used when neither the checkout nor the installed
       metadata answers. Keep it equal to ``pyproject.toml``.
   * - ``CHANGELOG.md``
     - A section ``## [vX.Y.Z] - YYYY-MM-DD`` (or the pre-release tag).
   * - The Git tag
     - ``vX.Y.Z``, equal to the version once the ``v`` is removed.

``publish.yml`` refuses a tag that does not match ``pyproject.toml``.

The checklist
-------------

1. **Choose the version** from the change, as above.
2. **Choose the branch.** Normal work comes from ``dev``. A stabilisation window
   uses ``release/X.Y``. A fix on an old line starts from the tag it fixes
   (``hotfix/X.Y.Z``). ``v1.0`` is frozen at ``v1.0.0``: do not release from it.
3. **Set the version** in ``pyproject.toml`` and ``_FALLBACK_VERSION``.
4. **Write the changelog.** Move the content of ``[Unreleased]`` to the new
   section and leave ``[Unreleased]`` empty for the next release. Use the Keep a
   Changelog categories: Added, Changed, Deprecated (only for an announced
   removal), Removed, Fixed, Security. The reason for a change belongs here. The
   release job takes the section as the body of the GitHub Release. It looks for
   the section of the tag and ends it at the next ``## [`` heading, so the section
   must exist and must not be the last one of the file.
5. **Check.** Run ``ruff check`` and ``ruff format --check``, the architecture gate
   and the tests of what changed, and build the docs
   (``make -C docs html-strict``). CI repeats them.
6. **Commit** the preparation in one line, for example
   ``chore(release): prepare v2.0.0b1``.
7. **Tag the commit** with an annotated tag, then send the tag to the remote.

   .. code-block:: bash

      git tag -a v2.0.0b1 -m "v2.0.0b1"
      git push origin v2.0.0b1

   A tag is immutable. A botched release is fixed by a new tag, never by moving
   the old one.
8. **Watch the jobs** (next section) and check the result.
9. **Merge back.** After a final release, merge the release branch into ``main``
   and ``dev``. After a maintenance release, merge the fix forward into ``dev`` if
   the bug is still there.

What the tag starts
-------------------

``Release / PyPI`` (``publish.yml``), on a ``v*.*.*`` tag or a manual dispatch with
an existing tag:

1. builds the sdist and the wheel, and checks that the tag equals the
   ``pyproject.toml`` version;
2. installs the wheel in a clean environment and writes a CycloneDX SBOM;
3. uploads to PyPI through Trusted Publishing (OpenID Connect, no token);
4. creates the GitHub Release, with the changelog section as its body and the
   distributions and the SBOM attached. A tag of the form ``vX.Y.ZaN``, ``bN`` or
   ``rcN`` is marked as a pre-release.

``Docs / Deploy Pages (multi-version)`` (``docs-deploy-pages.yml``) builds the
documentation of the pushed tag with a strict build and publishes it into its own
folder of ``docs.hydromodpy.fr``. Folders already published are kept. The same job
rewrites ``switcher.json``, the list the version menu of the site reads, from the
folders it finds on the ``gh-pages`` branch, with ``main`` marked as preferred.

Python installers ignore a pre-release unless asked, so users install one with
``pip install --pre hydromodpy`` or by exact version.

Hotfix
------

A regression in ``vX.Y.Z`` is fixed from the released tag: branch, apply the
minimal patch, and release ``vX.Y.(Z+1)``. A hotfix carries no feature. For an
older major line, branch from its maintenance branch (``maint/1.x``), which exists
only if maintenance of that line resumes.

After the release
-----------------

- Check the version on https://pypi.org/p/hydromodpy and the new folder on the
  documentation site.
- Check that ``switcher.json`` lists the version.
- Start recording the next changes under ``[Unreleased]``.
