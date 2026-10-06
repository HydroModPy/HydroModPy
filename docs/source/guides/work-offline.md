# Work offline: caches and lockfiles

After one run with network access, a project can run again with no network at all. The first
run stores every download in the data folder of the workspace and indexes it. A lockfile
records the SHA-256 digest of each stored file. A run started with `--frozen` then refuses
any download and any file that differs from the lockfile.

## What you need first

- A project that reads at least one API source. Step 3 of example 04, `step3_api_data.toml`,
  reads BD Topage and Hub'Eau. The example README says it needs network access at the first
  launch.
- The folder of example 04 with its data, and `hmp` on your path.
- One run with network access. A run cannot fill a cache it never reads.

The sources that contact a network host are listed in {doc}`../reference/data-sources`.
A source that reads your own files (`source = "custom"`) never does. If all your sources are
custom, there is nothing to cache and the project already works offline. See
{doc}`use-your-own-files`.

## 1. Find the cache of your project

The cache sits in the data folder of the workspace, `<workspace>/data/`. It holds:

- `cache.duckdb`, the index of the cache;
- one folder per variable, such as `data/hydrometry/` or `data/hydrography/`;
- next to each stored file, a sidecar `<file name>.json` with the source, the SHA-256 digest
  and the licence.

A station chronicle downloaded from an API is named
`<variable>_<provider>_<station>_<start>_<end>_<frequency>.csv`. The files and their sidecars
are the data. The index only finds them again.

The workspace of a project is found by the rules of {ref}`Where the files go
<workspace-folder>`. Example 04 sits under `examples/projects/`, and `examples/data/`
exists, so its cache is `examples/data/`. One workspace holds one cache for all its
projects. A station downloaded for one catchment serves the next one.

```{hmp-params}
workspace.root
workspace.data_dir
```

To put the cache somewhere else, for example on a shared disk, set the root in the file:

```toml
base_config = "step3_api_data.toml"

[workspace]
root = "/srv/hydromodpy"
```

Every command of this page that takes `--workspace` must then name the same folder.

## 2. Fill the cache once, online

From the folder of example 04, run the file that reads the APIs, with network access:

```bash
hmp run step3_api_data.toml
```

The data layer asks the cache before it asks the network, for each source:

- A grid (SIM2, for example) is reused when a stored grid covers the box and the period.
- A station chronicle is reused when its station is named and its period is covered. Only the
  missing days are downloaded.
- A station asked for by extent, with no `station_ids`, is never cached. It is searched again
  at every run.
- A station that returned no data is remembered as empty, and is not asked again.

So the file must name its stations and its period. Step 3 does both:

```{hmp-toml}
:file: step3_api_data.toml
:tables: data.hydrometry, data.hydrometry.sources
```

```{hmp-params}
data.hydrometry.sources.station_ids
data.hydrometry.date_start
data.hydrometry.date_end
```

Check what the run stored:

```bash
hmp data ls --workspace ../..
```

The workspace of example 04 is two folders up. The command prints one row per entry, with the columns `variable`, `source`, `station_id` and
`file_path`. Without `--workspace`, the command looks in `~/hydromodpy`. You can filter with
`--variable hydrometry` or `--provider hubeau`.

## 3. Pin what the run read

`hmp run` writes `hydromodpy.lock` at the end of every run that completes, next to
`project.toml`. It does so only when the workspace has a `data/cache.duckdb`. A run that
`hmp run` skips, because a completed run has the same configuration, writes nothing. The
lockfile belongs to the project, so it is versioned and travels with the project. A workspace has no lockfile of its own.

The file holds four parts:

- `[hydromodpy]`: the version, the git commit, the Python version and the schema versions;
- `[binaries]`: the digest and version text of the solver executables, when the run knows them;
- `[schema]`: the schema versions and a hash of the configuration schema;
- `[inputs]` and one `[[artefact]]` block per cache entry, with its SHA-256 digest and size.

The digests are the ones the index recorded when the file was registered. The command does
not hash the files again. The `fetched_at` of each entry is the time of the snapshot, not the
time of the download. The real download time is in the sidecar.

To write the lockfile without a run, for example after you added files by hand:

```bash
hmp dev lock update
```

Run from inside the project folder, as here, the command finds its project and its workspace
alone. The project is the nearest parent folder that holds `project.toml`. The workspace is the
nearest parent of the project that holds `data/` and `projects/`, or `workspace.toml`. From
elsewhere, name them: `--project` is the folder that owns the lockfile, and `--workspace` is the
folder that holds the cache. An entry whose file is missing from the disk is left out of the
lockfile.

## 4. Run without network

```bash
hmp run step3_api_data.toml --frozen --force
```

`--force` is needed here because you ran this file in section 2. Without it, `hmp run` finds a
completed run with the same configuration, prints
`Config identical to completed run '<name>' [<id>]; nothing to do.` and reads no data, so
the offline load is never tried.

`--frozen` does two things:

1. Before anything starts, it checks the lockfile against the cache. It stops on a missing
   lockfile, a missing cache, a missing file or a SHA-256 drift.
2. On a `simulation` workflow, it also holds during the whole run. The cache refuses a miss,
   and it refuses any entry that the lockfile does not list, instead of downloading. The
   constraint is released when the run ends.

A frozen run still writes the lockfile when it ends. The content is the same, and the
timestamps change. Add `--no-lock` to leave the file as it is.

`--frozen` refuses every download, and says so. For the DEM, the geology and the river
network, the refusal stops the run. For any other variable, such as the gauge of step 3, the
refusal is logged as `[ERROR] Load of '<variable>' failed: ...` and the run goes on without
that variable. Read the log after `load_data`. A run without `--frozen` also makes no request
for a source whose cache covers the request, but it downloads the rest.

## 5. Refresh a source on purpose

To download again, set `force_refresh` on that one source. Here Hub'Eau is asked again and
BD Topage stays cached:

```toml
base_config = "step3_api_data.toml"

[data.hydrometry]
sources__delete = true

[[data.hydrometry.sources]]
source = "hubeau"
product = "QmnJ"
station_ids = ["J001401001"]
force_refresh = true
```

```{hmp-params}
data.hydrometry.sources.force_refresh
```

Every variable has the same key under its own sources, for example
{toml}`force_refresh|data.hydrography.sources.force_refresh`.

Follow the order below. A refresh changes files, so a frozen run would stop on it.

1. Run once without `--frozen`, with `force_refresh = true`.
2. Remove the key, or set it back to `false`. Left on, it downloads at every run.
3. Run `hmp dev lock update`, so the lockfile pins the new files.
4. Run with `--frozen --force` again. The file is the same as before the refresh, so
   `--force` is needed for the run to load the data.

To drop entries instead, without downloading yet:

```bash
hmp data remove --workspace ../.. --variable hydrometry --provider hubeau
hmp data prune --workspace ../.. --older-than 90
```

`prune` removes the entries created more than N days ago, 30 by default. Neither command
deletes a file unless you add `--delete-files`. A file you provided yourself is never deleted,
only forgotten.

After an entry is removed, the next run without `--frozen` downloads it again. That is the
case the offline run must avoid.

## 6. Move the cache to another machine

Copy two things: the `data/` folder of the workspace, with `cache.duckdb`, and the project
folder, with `hydromodpy.lock`. The index stores paths relative to the workspace, so it works
from a new location. Then check it:

```bash
hmp dev lock verify
```

Run it from the project folder on the new machine, or name `--project` and `--workspace`. The
command prints `OK: catalog matches lockfile` when the two agree.

The archive commands are not a substitute for the copy:

```bash
hmp data archive cache.tar.gz --workspace ../..
hmp data restore cache.tar.gz --workspace ../..
```

`archive` writes a lockfile and the files of the cache, stored as `artefacts/<sha256>/<name>`.
It also writes a `hydromodpy.lock` into the folder of the archive. `restore` unpacks the
archive into `<workspace>/data/imported` and checks the digests. It does not put the files
back in `data/<variable>/` and does not touch the index. `hmp dev lock archive` and
`hmp dev lock restore` do the same, and `restore` writes to `<workspace>/data/restored` by
default.

## Check that it worked

- `hmp config check step3_api_data.toml` prints `OK:` and the path of the file.
- `hmp data ls --workspace ../..` lists the entries of the sources you ran.
- `hmp dev lock verify` prints `OK: catalog matches lockfile`. Add `--strict` to make a drift an error instead of a
  warning.
- Disconnect the network and run `hmp run step3_api_data.toml --frozen --force`. The run goes
  to the end with no `[ERROR]` line from the data layer.
- `hmp run step3_api_data.toml --debug` prints one line `<source> cache hit: <station>` for
  each station served from the cache.

## What can go wrong

The messages below exist in the code. The first block is the check before a frozen run. It
ends the command with exit code 14.

```text
--frozen: hydromodpy.lock not found at <path>; --frozen requires a prior run.
--frozen: Data cache not found at <path>; --frozen requires a populated workspace.
--frozen: <n> lockfile mismatch(es); first: <kind> on <path> (variable=<variable>)
```

- **No lockfile.** Run once without `--frozen`, or run `hmp dev lock update`.
- **No cache.** The run looks for `cache.duckdb` in the data folder of its own workspace. Check
  step 1, and `HMP_WORKSPACE`.
- **A mismatch.** `<kind>` is `sha256` when a file changed and `missing` when a file is gone.
  If you changed the file on purpose, run again without `--frozen`, with `--force` when the
  TOML did not change, so the new file is registered, then update the lockfile. `hmp dev lock update` alone keeps the old digest.

During a frozen run, the cache raises one of these. For a variable other than the DEM, the
geology and the river network, the message follows `[ERROR] Load of '<variable>' failed:` and
the run goes on:

```text
Frozen data mode forbids cache misses: <variable>/<source>/<station> is absent from the catalog at <path>.
Frozen data mode forbids catalog entries absent from hydromodpy.lock: <variable>/<source>/<station>.
Frozen data mode detected a SHA-256 mismatch for <variable>/<source>/<station>.
Frozen data mode forbids registering a custom file absent from hydromodpy.lock: <variable>/<source>/<station>.
```

- **A cache miss** means the run asks for data the cache does not hold: another station, a
  longer period, another box. Widen the period online first, then update the lockfile.
- **An entry absent from the lockfile** means a file entered the cache after the last
  `hmp dev lock update`.
- **A custom file absent from the lockfile** means you added a file to a `custom` source.
  Update the lockfile.

Without `--frozen`, a cache that does not cover the request sends the run to the network.
With no network the HTTP client gives up and raises:

```text
HTTP GET <url> failed after <n> retries
```

This is a `NetworkError`, code `HMPY.E205`. Run once online, or use `--frozen` to find the
source that is not cached.

`hmp dev lock update` and `hmp dev lock verify` have their own messages, and end with exit
code 10:

```text
Data cache not found: <path>
Lockfile not found: <path>
Workspace not found: <path>. Run 'hmp workspace init' first.
```

The `hmp data` commands print `Workspace <path> does not exist. Run 'hmp workspace init' first.`
when the folder given to `--workspace` is not there.

`hmp dev lock verify` ends with exit code 16 when it finds a mismatch, with or without
`--strict`. It also warns when the configuration schema has changed since the lockfile was
written. With `--strict` this warning is an error.

`hmp data ls` prints `(no cache found)` when the workspace has no `data/cache.duckdb`, and
`(empty cache - drop files in data/<variable>/ then run 'hmp run')` when the index has no
entry.

The solver executables do not go through the cache. They are fetched at the first solver use.
To have them before you disconnect, run `hmp install-binaries`. They go to the `bin` folder of
the HydroModPy cache directory, which `HMP_CACHE_HOME` moves.

## Where to go next

- {doc}`use-your-own-files` if you prefer to read your own files and never contact an API.
- {doc}`get-the-data` for what each data section asks for.
- {doc}`troubleshooting` for other messages.
- {doc}`../reference/cli/data` and {doc}`../reference/cli/dev` for every option of the commands
  used here.
- {doc}`../reference/cli/run` for `--frozen` and `--no-lock`.
