# Release Policy

This document defines how HydroModPy is versioned, tagged, and published.
It is the contract between maintainers and users about what a version
number means and how a release reaches PyPI.

## SemVer

HydroModPy follows [Semantic Versioning 2.0.0](https://semver.org/).
Given a version `MAJOR.MINOR.PATCH`:

- **MAJOR** (`X.0.0`)
  - Incompatible API change.
  - Removal of a documented feature, CLI verb, or config field.
  - Breaking change to a config schema (renamed key, changed type,
    tightened validation that rejects previously valid input).
- **MINOR** (`X.Y.0`)
  - Backward-compatible feature addition.
  - New config field with a default.
  - New CLI verb.
  - New solver backend or new public function.
- **PATCH** (`X.Y.Z`)
  - Backward-compatible bug fix only.
  - No new fields, no new public API.

Pre-releases use `X.Y.ZrcN` (e.g. `1.0.0rc1`).

## Deprecation cycle

A public symbol or config field marked deprecated must:

1. Stay available for at least one full MINOR release with a
   `DeprecationWarning` (or schema-level deprecation note).
2. Be removed in the next MINOR, never in a PATCH.
3. Be tracked in `LEGACY_REMAINING.md` until removal.

Internal symbols (modules or names starting with `_`) carry no
backward-compatibility guarantee and may change in any release.

## Tagging discipline

- Every release has exactly one git tag of the form `vX.Y.Z`.
- The tag is annotated (`git tag -a`) and, when a maintainer key is
  available, GPG-signed (`git tag -s`).
- The tag message is the `[vX.Y.Z]` section of `CHANGELOG.md`.
- Tags are immutable. A botched release is fixed by tagging a new
  PATCH, never by force-moving an existing tag.

## Publication flow

1. Open a release PR that:
   - Bumps `version` in `pyproject.toml`.
   - Moves the `[Unreleased]` section of `CHANGELOG.md` to a new
     `## [vX.Y.Z] - YYYY-MM-DD` section and reopens an empty
     `[Unreleased]`.
2. After the PR merges, tag the merge commit `vX.Y.Z` and push the
   tag.
3. The `publish.yml` workflow takes over:
   - Builds wheel and sdist with `python -m build`.
   - Uploads to PyPI via `pypa/gh-action-pypi-publish` using
     Trusted Publishers (OIDC). No API tokens are stored as secrets.
   - Creates a GitHub release whose body is the matching CHANGELOG
     section, with the wheel and sdist attached as assets.
4. Tagging is the only manual gate. Auto-tagging on PR merge is
   intentionally not used; tagging signals deliberate release intent.

## Trusted Publishers configuration

The PyPI project `hydromodpy` is configured as a Trusted Publisher
bound to:

- repository workflow: `.github/workflows/publish.yml`
- GitHub environment: `pypi`

Any change to the workflow path or environment name requires updating
the Trusted Publisher configuration on PyPI before the next release.

## Hotfix policy

A regression in `vX.Y.Z` is fixed by branching from the tag, applying
the minimal patch, and releasing `vX.Y.(Z+1)`. Hotfixes never carry
new features.
