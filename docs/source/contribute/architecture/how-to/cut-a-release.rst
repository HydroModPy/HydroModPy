Cut a release
=============

A release is a Git tag. The tag starts three jobs: the publication to PyPI, the
GitHub Release, and the build of the documentation for that version. This page
is the maintainer's checklist. What each kind of version may change is in
:doc:`/about/versions`, the only statement of that contract.

Version and tag syntax
----------------------

Versions follow Semantic Versioning for meaning and PEP 440 for the string.

.. code-block:: text

   MAJOR.MINOR.PATCH          2.0.0
   MAJOR.MINOR.PATCHaN        2.0.0a1     alpha
   MAJOR.MINOR.PATCHbN        2.0.0b1     beta
   MAJOR.MINOR.PATCHrcN       2.0.0rc1    release candidate

The Git tag is the version with a leading ``v``: ``v2.0.0rc1``, ``v2.0.0``. Do not
invent other forms such as ``release-v2`` or ``v2-beta``.

Five places must agree
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Where
     - What
   * - ``pyproject.toml``
     - ``[project] version``. This is the source of the package version, and a
       source checkout reads its ``__version__`` from it.
   * - ``CITATION.cff``
     - ``version``. Keep it equal to ``pyproject.toml``. It has no ``doi`` of the
       release: the DOI of a version exists only after Zenodo archives it, so add
       it to ``identifiers`` then.
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

1. **Choose the version** from the change, with :doc:`/about/versions`.
2. **Choose the branch.** Normal work comes from ``dev``. A stabilization window
   uses ``release/X.Y``. A fix on an old line starts from the tag it fixes
   (``hotfix/X.Y.Z``). ``v1.0`` is frozen at ``v1.0.0``: do not release from it.
3. **Set the version** in ``pyproject.toml`` and ``_FALLBACK_VERSION``.
4. **Write the changelog.** Move the content of ``[Unreleased]`` to the new
   section and leave ``[Unreleased]`` empty for the next release. Put no ``---``
   rule right under the empty heading: the docs include the file, and the strict
   build refuses a section that begins with a rule. Use the Keep a
   Changelog categories: Added, Changed, Deprecated (only for an announced
   removal), Removed, Fixed, Security, plus ``Numbers`` for anything that changes
   a number of a run. The reason for a change belongs here. The
   release job takes the section as the body of the GitHub Release. It looks for
   the section of the tag and ends it at the next ``## [`` heading, so the section
   must exist and must not be the last one of the file.
5. **Read the numbers section.** Each entry names the quantity and the size of the
   change, and has its row in ``hydromodpy/schema/changes.toml``, under the rule of
   `Changing a number`_. The bullets come from that file: run
   ``python -m tools.changes_changelog`` and it prints the difference when the block
   between ``<!-- numbers:begin -->`` and ``<!-- numbers:end -->`` is out of date.
   ``python -m tools.changes_changelog --write`` writes it. A pin moved since the last
   tag has its row too, under the rule of `Moving a pinned binary`_.
6. **Review the surface snapshots.** Read what changed since the last tag:
   ``git diff vX.Y.Z -- tests/unit/architecture/surface/``. Each removed or renamed
   line must be in the changelog with both names, and each TOML key it removes must
   be in ``removed_toml_keys.tsv``, with its ``[[migration]]`` row in
   ``hydromodpy/schema/changes.toml``. The row stays in the register after its delay,
   because a live file is then refused with the new name and a sealed run still reads
   it, so it is never removed. What does go is a name of ``_lazy.py`` or
   ``conventions.py`` past its delay, which ``tests/unit/architecture`` names, and the
   list ``hydromodpy/config/prerelease_forms.txt``, which goes in 2.3.0.
7. **Regenerate the example catalog.** ``hmp example add`` fetches the files at the
   tag of the installed version and checks them against ``catalog.toml``. Run
   ``python -m tools.dev examples manifest`` and commit the result, or every download of the
   release fails on a checksum. Then run ``python tools/ci/check_example_catalog.py``
   from the commit to tag. It hashes each file the catalog names, as CI and the
   release gate do.
8. **Check.** Run ``ruff check`` and ``ruff format --check``, the architecture gate
   and the tests of what changed, and build the docs
   (``make -C docs html-strict``). CI repeats them.
9. **Commit** the preparation in one line, for example
   ``chore(release): prepare v2.0.0b1``.
10. **Tag the commit** with an annotated tag, then send the tag to the remote.

    .. code-block:: bash

       git tag -a v2.0.0b1 -m "v2.0.0b1"
       git push origin v2.0.0b1

    A tag is immutable. A botched release is fixed by a new tag, never by moving
    the old one.
11. **Watch the jobs** (next section) and check the result.
12. **Merge back.** After a final release, merge the release branch into ``main``
    and ``dev``. After a maintenance release, merge the fix forward into ``dev`` if
    the bug is still there.
13. **Open the next version on dev.** Set ``pyproject.toml`` and
    ``_FALLBACK_VERSION`` of ``dev`` to the next minor version with ``.dev0``, for
    example ``2.1.0.dev0`` after ``v2.0.0``. A run seals the version it was made with,
    and a ``[[bug]]`` row covers the released versions, ``versions = "<2.1.0"``. A
    run of ``dev`` that still said ``2.0.0`` would carry for good a bug that ``dev``
    has fixed. ``tests/unit/architecture/test_changes_register.py`` fails when a row
    covers the version of the tree.

Changing a number
-----------------

A fix that moves a number of a run is allowed in a minor version and in a patch when
the old number was wrong. It carries three things in the commit that makes it:

- an entry under ``Numbers`` in ``CHANGELOG.md``, with the quantity and the size of
  the change, measured before and after. It is the ``text`` of the row below, and
  ``python -m tools.changes_changelog --write`` copies it;
- a ``[[bug]]`` row in ``hydromodpy/schema/changes.toml``, with the versions it
  touches and the quantities it changes, so that a run stored before the fix reads as
  ``exploratory``. A rule or a default that moves a number without a bug is a
  ``[[recipe]]`` of effect ``numbers`` or a ``[[default]]`` row instead;
- the goldens it moves, under the rule of ``tests/regression/README.md``.

Moving a default is another thing: see the Defaults section of :doc:`/about/versions`.

Moving a pinned binary
----------------------

HydroModPy downloads two native files at run time, and each one is pinned by a tag
and by a sha256 per platform asset. A download that hashes to anything else is
refused and never reaches the disk under its name.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - What
     - Where it is pinned
   * - MODFLOW executables and ``libmf6`` (``MODFLOW-ORG/executables``)
     - ``DEFAULT_RELEASE`` and ``RELEASE_ASSETS`` in
       ``hydromodpy/solver/modflow_common/binaries.py``. One zip per platform holds
       every solver, so one digest covers them all.
   * - The HELP3O extension (``HydroModPy/HELP3O-binaries``)
     - ``HELP3O_RELEASE`` and ``HELP3O_ASSETS`` in
       ``hydromodpy_annex/physics/pyhelp/core/paths.py``. One asset per platform
       and Python version.

A new release is a number change until proven otherwise, because a new solver build
can move a run even when no line of HydroModPy moved. So a bump is never a one-line
change. It goes through these steps, in the commit that moves the pin:

1. Read the digests from GitHub, without a download:

   .. code-block:: bash

      gh api repos/MODFLOW-ORG/executables/releases/tags/<tag> \
        --jq '.assets[] | [.name, .digest] | @tsv'

   Write the tag and every digest in the table. A Python version or a platform the
   new tag adds goes in the table, and one it drops is refused from then on, so say
   so in the changelog.
2. Install the new binaries and run the regression tiers and the validation cases
   against them, with ``tests/regression/README.md``. Move a golden only with its
   stated reason, and update the versions ``tests/TOLERANCES.md`` names.
3. Write the entry under ``Numbers`` in ``CHANGELOG.md``, with the old and new
   release and the size of the change, measured before and after. If nothing moved,
   the entry says that and names what was run. If a number moved, this is
   `Changing a number`_, with its row in ``hydromodpy/schema/changes.toml``.

A digest that changes while the tag stays is a new release too: the asset was
replaced upstream, so the same steps apply. An existing cache is never refreshed by
a bump. ``hmp install-binaries --upgrade`` is what moves a user to the new pin.

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
``pip install --pre hydromodpy`` or by exact version. Pages for users never show
the flag or a version number. The number lives in ``pyproject.toml`` only.

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
