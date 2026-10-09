# Versions and stability

This site documents version {{ release }}. It is a pre-release of the 2.0 line. Versions
2.0.0a1 to 2.0.0a4 are published on [PyPI](https://pypi.org/project/hydromodpy/). What each
one changed is in the {doc}`changelog <changelog>`.

## What a version number says

HydroModPy follows [Semantic Versioning](https://semver.org/). A pre-release adds a suffix
that [PEP 440](https://peps.python.org/pep-0440/) defines: `a` for alpha, `b` for beta and `rc`
for release candidate, then a number, as in `2.0.0a4`.

- **Major** (`X.0.0`): a change that makes you edit your files. A removed or renamed TOML key,
  Python function or `hmp` verb, a new storage format, a different solver behaviour.
- **Minor** (`X.Y.0`): a compatible addition. A new solver, a new optional key with a default,
  a new verb or function.
- **Patch** (`X.Y.Z`): a bug fix only. No new public name, no change you have to adapt to.

A removed name is not kept as an alias. If a change needs you to edit a file, it is a major
change, unless it lands in a pre-release before the stable version.

| Stage | Example | What to expect |
|---|---|---|
| Alpha | `2.0.0a4` | Public testing. Keys, API and storage can still change. |
| Beta | `2.0.0b1` | Feature complete. The contract changes only to fix a blocker. |
| Release candidate | `2.0.0rc1` | Only blocking fixes land. |
| Final | `2.0.0` | The version to recommend to users. |

## Install a version

`pip` skips pre-releases unless you ask for them. To follow the 2.0 line, or to pin an exact
release so a project reads the same keys tomorrow, such as {{ release }} now:

```bash
pip install --pre hydromodpy
pip install hydromodpy==<version>
```

A project written for version 1 stays on the tag `v1.0.0` of the repository. Version 1 is frozen
on the `v1.0` branch. It gets no new work.

## Which documentation to read

The version switcher in the header offers three sites.

| Site | Documents |
|---|---|
| `main` | The published line of version 2. Read this one by default. |
| `dev` | The development branch. It can describe changes not released yet. |
| `v1.0` | Version 1, frozen. It is no longer updated. |

The documentation of each alpha is not kept apart. Read `main`, and use the
{doc}`changelog <changelog>` and {doc}`What changed in the TOML </reference/changes>` to see
how the keys moved between releases.
