# Versions and stability

This site documents version {{ release }}. It is a pre-release of the 2.0 line. Versions
2.0.0a1 to 2.0.0a5 are published on [PyPI](https://pypi.org/project/hydromodpy/). What each
one changed is in the {doc}`changelog <changelog>`.

## What a version number says

HydroModPy follows [Semantic Versioning](https://semver.org/). A pre-release adds a suffix
that [PEP 440](https://peps.python.org/pep-0440/) defines: `a` for alpha, `b` for beta and `rc`
for release candidate, then a number, as in `2.0.0a5`.

The rules below hold from `2.0.0` on, and this page is their only statement. The goal is that
the 2 line can grow for years without a version 3, so a change that a user can absorb never
needs a major version.

### Frozen for the whole 2 line

A run you stored stays readable. Its folder layout, its Parquet and Zarr schemas, its manifest
and its provenance can be read by every later 2.x, and so can the keys of its frozen
`config.toml`. Only a major version can change this. A stored format can gain a new version
inside the line, and the build that writes it then also reads the older ones.

The index `.hmp/index.duckdb` is outside this promise, because it is derived from the run
folders. `hmp catalog reindex` rebuilds it at any time.

### Can change in a minor version, with a migration

This covers the name or the place of a TOML key, an `hmp` command or flag, a name of
`hydromodpy.__all__` and the shape of a config table.

The old name keeps working for two minor versions, the one that changes it included. A key
renamed in 2.3 still loads in 2.3 and 2.4, and can go in 2.5. While it works it prints a warning
that gives the old name and the new one, once per key and per file. `hmp doctor --fix-config
<file>` rewrites your file and the files it inherits, and keeps your comments. An old name of Python, or an old `hmp` command
or flag, prints a `FutureWarning` with both names and then does what the new one does. The
changelog lists the rename under `Changed` with both names, and later its removal under `Removed`.

### Numbers

A fix that changes the numbers of a run (a head, a flow, a score) is allowed in a minor version
and in a patch when the old number was wrong. A scientific correction does not wait. The
changelog lists it under `Numbers` with the size of the change, and it gets an entry in the
register of known issues, `hydromodpy/results/known_issues.toml`. A run stored with an older
version keeps its numbers and its version stamp and is never rewritten. `Run.label()` then
calls it `exploratory` and names the issue.

### Defaults

A file that does not say which defaults it wants follows the defaults of 2.0, for the whole 2
line. So a key you did not write never changes your numbers. The day a default has to move, an
optional `edition` key comes with it, and only a file that writes this key gets the new value.
The key does not exist yet, because no default has moved.

### What makes two runs the same

Two runs are the same computation when their configurations, the bytes of their input files,
the mesh engine and the code that computes agree. A release that only touches figures, commands
or this documentation keeps that identity, so an identical run is not computed again, and an edit
of a solver changes it. A configuration counts by what it writes: a key written at its default value
is another identity than no key, because a validator can tell the two apart, and it costs one more
computation at worst. A calibration is not part of the identity of the run it promotes, whose file
holds its own solve.

### What a sealed run keeps

A run seals `config.toml`, what it was given, overrides included, and `config.resolved.toml`, the
same with every default written. `hmp run <run>/config.toml --frozen` compares the two with what
this version would use and refuses a key that moved. It also checks the digests of the inputs the
run recorded, and warns when the solver binary differs. `hmp catalog rerun` warns on the same keys
and records them in the lineage of the new run.

### Experimental

Anything marked experimental may change in any minor version, without the delay above.

- In a TOML file: the whole `[calibration]` section, the VI and TS runtimes of Boussinesq with
  their settings, `partition_release_depth_m`, `transport.modflow6prt`, the MODPATH block, the
  HFB barriers, the parameters of the soil reservoir beyond its budget,
  `geographic.domain_extent` and the `custom` backend. The
  {doc}`parameter reference </reference/parameters/index>` marks each key. A run lists the
  experimental keys its file writes in one line of its log, and `hmp config check` shows them.
- In Python: the shape of `CalibrationReport`, and the `solver`, `solver.extractor` and
  `calibration.evaluator` plugin ports, as {doc}`the contracts page
  </contribute/architecture/contracts>` details.
- The sidecars of `validity_frame`.
- Every command under `hmp dev`.

### Patch

A patch fixes bugs. It adds no public name, and it asks nothing of you. It can still change a
number that was wrong, under the rule above.

### What the rules cover

The names are the ones the generated pages list: the {doc}`Python reference
</reference/python/index>`, the {doc}`command line reference </reference/cli/index>` with its
{doc}`exit codes </reference/cli/exit-codes>`, and the {doc}`parameter reference
</reference/parameters/index>`. A module path outside `hydromodpy.__all__` is internal, except the
short list on {doc}`the contracts page </contribute/architecture/contracts>`. So is any `HMP_*`
variable that {doc}`its generated page </contribute/architecture/generated/environment>` does
not give to users.

### Pre-releases

A pre-release makes none of these promises.

| Stage | Example | What to expect |
|---|---|---|
| Alpha | `2.0.0a5` | Public testing. Keys, API and storage can still change. |
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
