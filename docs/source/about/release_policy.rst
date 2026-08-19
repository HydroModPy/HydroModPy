Release and versioning policy
=============================

This page defines how HydroModPy is versioned, tagged, branched, and
published. It is the contract between maintainers and users about what a
version number means and how a release reaches PyPI.

Version syntax
--------------

HydroModPy uses `Semantic Versioning 2.0.0 <https://semver.org/>`_ for
release meaning and `PEP 440 <https://peps.python.org/pep-0440/>`_ for
Python-compatible version strings.

Final releases use:

.. code-block:: text

   MAJOR.MINOR.PATCH

Pre-releases use:

.. code-block:: text

   MAJOR.MINOR.PATCHaN
   MAJOR.MINOR.PATCHbN
   MAJOR.MINOR.PATCHrcN

Git tags always add the leading ``v``:

.. code-block:: text

   v1.1.0
   v1.1.1
   v2.0.0a1
   v2.0.0b1
   v2.0.0rc1
   v2.0.0

Do not create tags such as ``release-v2``, ``v2-beta``, ``v2.0-alpha``,
or ``pre-refonte-v2``. Historical non-conforming tags remain as archive
markers, but new release tags must follow the format above.

Version meaning
---------------

Given a final version ``MAJOR.MINOR.PATCH``:

- **MAJOR** (``X.0.0``): incompatible public contract change. Examples:
  removed or renamed public API, CLI verb, config field, storage format,
  solver behavior, or workflow behavior that requires user migration.
- **MINOR** (``X.Y.0``): backward-compatible feature addition. Examples:
  new solver backend, optional config field with a default, new CLI verb,
  new public function, or new report output that does not break existing
  users.
- **PATCH** (``X.Y.Z``): backward-compatible bug fix only. No new public
  API, no config schema change, no behavior change that users must adapt
  to.

HydroModPy does not keep compatibility shims for removed public contracts.
If a change requires users to edit their code, TOML config, CLI calls, or
stored project layout, it is a ``MAJOR`` change unless it happens before a
stable release in an ``a``, ``b``, or ``rc`` pre-release.

Pre-release stages
------------------

Use pre-releases when code should be published for testing before the
contract is final.

.. list-table::
   :header-rows: 1
   :widths: 18 30 42

   * - Stage
     - Example
     - Use
   * - Alpha
     - ``2.0.0a1``
     - Public testing while the API, config, storage, or behavior can still
       change.
   * - Beta
     - ``2.0.0b1``
     - Feature-complete release line. The public contract should change only
       when needed to fix a release blocker.
   * - Release candidate
     - ``2.0.0rc1``
     - Candidate for the final release. Only release-blocking fixes should
       land.
   * - Final
     - ``2.0.0``
     - Stable release recommended to normal users.

Python installers ignore pre-releases by default unless the user asks for
them explicitly:

.. code-block:: bash

   pip install hydromodpy
   pip install --pre hydromodpy
   pip install hydromodpy==2.0.0b1

Branch model
------------

Branches are moving development lines. Tags are immutable release points.
Users should identify released code through tags and GitHub Releases, not
through branch names.

Long-lived branches:

.. list-table::
   :header-rows: 1
   :widths: 22 50

   * - Branch
     - Role
   * - ``main``
     - Current v2 line and future stable default branch. It carries version
       ``2.0.0a1``, which is not tagged or released yet.
   * - ``dev``
     - Active integration branch for the next v2 pre-release.
   * - ``v1.0``
     - Published v1 line, frozen at the ``v1.0.0`` tag. It is kept for users
       who still need v1, it does not receive the v2 work, and it is not
       actively maintained.
   * - ``maint/1.x``
     - Optional maintenance branch for ``1.*`` releases if active v1
       maintenance resumes. Do not use this name for a frozen branch.

Short-lived branches:

.. list-table::
   :header-rows: 1
   :widths: 22 50

   * - Branch
     - Role
   * - ``feat/<name>``
     - Feature work.
   * - ``fix/<name>``
     - Bug fix work.
   * - ``docs/<name>``
     - Documentation-only work.
   * - ``release/2.0``
     - Stabilization branch for ``2.0.0`` pre-releases and the final
       ``2.0.0``.
   * - ``hotfix/1.0.1``
     - Temporary branch for a single urgent patch release.

The frozen v1 line lives on ``v1.0`` only. Do not open other long-lived v1
or v2 branches, use ``maint/1.x`` only for active maintenance, and identify
exact released code through tags such as ``v1.0.0`` or ``v2.0.0a1``.

Current layout: frozen v1 alongside the v2 pre-release
------------------------------------------------------

The v1 line is published and frozen on its own branch. The current line is
the v2 pre-release:

.. code-block:: text

   main        current v2 line, version 2.0.0a1, not released yet
   dev         active integration for the next v2 pre-release
   v1.0        frozen v1.0.0 source and docs with an upgrade warning
   release/2.0 temporary v2 stabilization branch

Use ``maint/1.x`` only if the project decides to actively maintain v1
again. A frozen branch is an archive branch, not a maintenance branch.

Typical tags during the v2 transition:

.. code-block:: text

   v1.0.0       final v1 release kept on the v1.0 branch
   v2.0.0a1     first public v2 alpha from main
   v2.0.0b1     v2 beta
   v2.0.0rc1    v2 release candidate
   v2.0.0       final v2 release on main

Archive branch warning
----------------------

The ``v1.0`` documentation must show a visible warning on the home page,
install page, and contributor page:

- v1 is frozen and no longer updated.
- Existing v1 users can keep using tagged releases such as ``v1.0.0``.
- New work should move to ``main`` and the v2 documentation.
- The warning should link to
  ``https://hydromodpy-docs.readthedocs.io/en/main/``.

Tagging discipline
------------------

- Every published release has exactly one Git tag.
- Final tags use ``vX.Y.Z``.
- Pre-release tags use ``vX.Y.ZaN``, ``vX.Y.ZbN``, or ``vX.Y.ZrcN``.
- Tags are immutable. A botched release is fixed by tagging a new release,
  never by force-moving an existing tag.
- Prefer annotated tags (``git tag -a``). Use signed tags when maintainer
  keys are available.
- The tag must match the package version exactly after removing the leading
  ``v``.

The following files must agree before a tag is pushed:

.. code-block:: text

   pyproject.toml
   hydromodpy/core/version.py
   CHANGELOG.md
   Git tag

``pyproject.toml`` is the package metadata source.
``hydromodpy/core/version.py`` contains the source-checkout fallback and
must be kept in sync while the project uses a static package version.

Release flow
------------

1. Decide the target version from the change:

   - bugfix on the stable line: ``PATCH``
   - compatible feature: ``MINOR``
   - breaking public contract change: ``MAJOR``
   - unfinished public testing: add ``aN``, ``bN``, or ``rcN``

2. Create the correct branch:

   - normal work from ``dev``
   - current v2 release work from ``main`` or ``release/2.0``
   - frozen v1 documentation from ``v1.0`` only for legacy warnings
   - active v1 maintenance from ``maint/1.x`` only if maintenance resumes
   - stabilization from ``release/X.Y``

3. Update the version in ``pyproject.toml`` and
   ``hydromodpy/core/version.py``.

4. Move ``CHANGELOG.md`` content from ``[Unreleased]`` to a section named:

   .. code-block:: text

      ## [vX.Y.Z] - YYYY-MM-DD
      ## [vX.Y.ZaN] - YYYY-MM-DD
      ## [vX.Y.ZbN] - YYYY-MM-DD
      ## [vX.Y.ZrcN] - YYYY-MM-DD

5. Run the required quality checks for the release branch. At minimum,
   run ``ruff check --fix .`` and ``ruff format .`` before the release
   commit. Run targeted tests or docs builds according to the changed area.

6. Commit the release preparation with a Conventional Commit subject, for
   example:

   .. code-block:: text

      chore(release): prepare v2.0.0b1

7. Tag the release commit:

   .. code-block:: bash

      git tag -a v2.0.0b1 -m "v2.0.0b1"
      git push origin v2.0.0b1

8. The ``publish.yml`` workflow builds the distributions, verifies that the
   tag matches ``pyproject.toml``, uploads to PyPI, and creates the GitHub
   Release. Tags containing ``aN``, ``bN``, or ``rcN`` must be marked as
   GitHub pre-releases.

9. After a final release, merge the release branch back into ``main`` and
   ``dev``. After a maintenance release, merge the maintenance fix forward
   into ``dev`` if the bug still exists there.

Hotfix policy
-------------

A regression in ``vX.Y.Z`` is fixed by branching from the released tag,
applying the minimal patch, and releasing ``vX.Y.(Z+1)``. Hotfixes do not
carry new features.

For a maintained older major line, branch from the relevant maintenance
branch. Do not use ``v1.0`` for hotfix work unless it has first been
promoted back to an active maintenance branch.

.. code-block:: text

   maint/1.x -> hotfix/1.0.4 -> v1.0.4

Changelog policy
----------------

``CHANGELOG.md`` follows Keep a Changelog categories. Use:

- ``Added`` for new features.
- ``Changed`` for behavior or public contract updates.
- ``Deprecated`` only for announced future removal. Do not add compatibility
  shims solely for deprecation.
- ``Removed`` for deleted features or files.
- ``Fixed`` for bug fixes.
- ``Security`` for security improvements.

Each published tag must have a matching changelog section. Pre-releases get
their own sections because users may install and cite them.

See also
--------

- :doc:`changelog` for shipped releases.
- :doc:`../contribute` for contributor setup and pull request workflow.
- ``CONTRIBUTING.md`` at the repository root for the contributor quick start;
  this page is the single source of truth for versions, tags, and branches.
- ``SECURITY.md`` at the repository root for supported security versions.
