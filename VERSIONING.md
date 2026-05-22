# HydroModPy versioning guide

HydroModPy uses Semantic Versioning for release meaning and PEP 440 for
Python-compatible version strings.

## Official version format

Final releases:

```text
MAJOR.MINOR.PATCH
```

Pre-releases:

```text
MAJOR.MINOR.PATCHaN
MAJOR.MINOR.PATCHbN
MAJOR.MINOR.PATCHrcN
```

Git tags add the leading `v`:

```text
v1.1.0
v1.1.1
v2.0.0a1
v2.0.0b1
v2.0.0rc1
v2.0.0
```

Do not create new release tags such as `release-v2`, `v2-beta`,
`v2.0-alpha`, or `pre-refonte-v2`.

## What to bump

- `PATCH`: compatible bug fix only, for example `1.0.1`.
- `MINOR`: compatible feature or public addition, for example `1.1.0`.
- `MAJOR`: incompatible public contract change, for example `2.0.0`.

Use `aN`, `bN`, or `rcN` when publishing code for testing before the final
release:

- `aN`: alpha, public testing while the contract can still change.
- `bN`: beta, feature-complete line with only blocker-driven contract changes.
- `rcN`: release candidate, final unless a release blocker appears.

## Branch roles

Branches are moving development lines. Tags are immutable release points.
Users should identify exact released code through tags and GitHub Releases.

Long-lived branches:

```text
master       latest stable final release line
dev          active integration for the next release
maint/1.x    optional v1 maintenance line when dev has moved to v2
```

Short-lived branches:

```text
feat/<name>
fix/<name>
docs/<name>
release/2.0
hotfix/1.0.1
```

Do not use `v1` or `v2` as long-lived branch names. Use `maint/1.x` for a
maintained major line and exact tags such as `v1.0.3` for releases.

## Release checklist

1. Choose the target version from the change type.
2. Update `pyproject.toml`.
3. Update the fallback in `hydromodpy/core/version.py`.
4. Move `CHANGELOG.md` entries from `[Unreleased]` to
   `## [vX.Y.Z] - YYYY-MM-DD` or the matching pre-release tag.
5. Run `ruff check --fix .` and `ruff format .`.
6. Run targeted tests or docs builds for the changed area.
7. Commit with a Conventional Commit subject, for example
   `chore(release): prepare v2.0.0b1`.
8. Create an annotated tag:

   ```bash
   git tag -a v2.0.0b1 -m "v2.0.0b1"
   git push origin v2.0.0b1
   ```

9. Let `.github/workflows/publish.yml` build, publish, and create the GitHub
   Release.
10. Merge final release branches back into `master` and `dev`. Merge
    maintenance fixes forward into `dev` when still applicable.

Full policy: `docs/source/about/release_policy.rst`.
