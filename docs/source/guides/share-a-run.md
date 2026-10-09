# Share a run

```{hmp-task}
Task
: Hand a finished run to someone who cannot reach your machine.

Time
: A few minutes. The package of step 1 took 8 s to write.

Needs
: A completed run in a project, and a project to receive it.

Gives
: A `.hmp` file the other side imports, and optional STAC, RO-Crate and PROV descriptions.
```

A run lives in the folder `runs/<name>/` of a project, and the index of the project is
derived from it. To give it away, you give a package: one file that holds the run, its
tables, the input files it read, and a checksum of every file. The other side imports it
into a project of its own.

This page uses the run `nancon_step1_minimal` of step 1. Any completed run works the same way.

## 1. Choose what to send

`hmp export --format` takes four values that describe the whole run instead of one variable.

| You want | `--format` | File | Written to |
|---|---|---|---|
| The run itself, to open it elsewhere | `package` | `<run>.hmp` | `share/<run>/` |
| A record for a catalogue of geospatial assets | `stac` | `stac-item.json` | `runs/<run>/` |
| A record for a research data repository | `rocrate` | `ro-crate-metadata.json` | `runs/<run>/` |
| How the run was made, as PROV | `prov` | `prov.jsonld` | `runs/<run>/` |

The maps and tables of a run, for people who use a GIS, are another task:
{doc}`hand-off-to-gis`.

## 2. Write the package

::::{tab-set}

:::{tab-item} Command line

```bash
hmp export nancon_step1_minimal all --format package
```

```text
/…/share/nancon_step1_minimal/nancon_step1_minimal.hmp
Exported 1 file(s)
```

Run it from the project folder, or give the folder with `-w`.
:::

:::{tab-item} Python

```python
import hydromodpy as hmp

with hmp.open(".", read_only=False) as cat:
    paths = hmp.export(cat["nancon_step1_minimal"], "all", format="package")
```

Open the catalog for writing. A catalog opened for reading only still writes the file, but
the export is then missing from the audit log, and the call logs
`audit emission failed for export`.
:::

::::

The three descriptions are written the same way. Without `--folder` or `--file`, each one
goes inside the run folder, because the paths it lists are relative to that folder:

```bash
hmp export nancon_step1_minimal all --format stac
hmp export nancon_step1_minimal all --format rocrate
hmp export nancon_step1_minimal all --format prov
```

The STAC item carries the extent of the run in WGS 84 and one asset per file or folder of
the run folder. The RO-Crate lists the same files, the licence of the run and the action that made
it. The PROV file records the software, the solver and the input files.

## 3. Know what the package holds

A package is a tar archive compressed with Zstandard. It holds:

- `manifest.json`, the format version and the SHA-256 digest of every other file;
- `catalog_snapshot.duckdb`, the rows of the run in the index;
- `fields.zarr.zip`, the field arrays, and `parquet/`, the tables;
- `run/`, the seal of the run folder: its manifest, its provenance and its frozen
  `config.toml`;
- `inputs/`, a copy of each input file the run read, with `inputs/manifest.json`.

The package of step 1 is 19.6 MB. It carries the regional DEM the catchment was cut from, so
its size follows your data, not the size of the run. The figures of the run folder are not in
the package. The receiver draws them again.

## 4. Check what you are about to send

The package records where and by whom the run was made. Nothing in HydroModPy removes it:

- `run/config.toml` and `inputs/manifest.json` hold the absolute paths of the project and of
  each input file on your machine, which show your user name.
- `run/provenance.json` holds `platform.hostname` and `platform.user`.
- The RO-Crate names the licence of the run. It reads `LicenseRef-undetermined` when an input
  file states no licence.

Declare who you are and under which licence once per workspace. The first run of a workspace
warns:

```text
Runs of this workspace are sealed without creator_name, creator_institution and a known
licence. Add creator_name = "..." and creator_institution = "..." under [workspace] in
workspace.toml; a licence comes from the 'license' key of each input sidecar (<file>.json).
```

The sidecar `<file>.json` of an input file is a JSON object. Its `license` key holds an SPDX
identifier, for example `{"license": "CC-BY-4.0"}`. A file downloaded from a provider gets its
licence from the provider. The list is {doc}`../reference/data-sources`.

## 5. Receive a package

Run the command in the project that receives the run, or give it with `-w`.

::::{tab-set}

:::{tab-item} Command line

```bash
hmp catalog import nancon_step1_minimal.hmp
```

```text
imported 1 run(s): a7c951a6
```

```bash
hmp catalog ls
hmp viz show nancon_step1_minimal watershed_id_card
```
:::

:::{tab-item} Python

```python
import hydromodpy as hmp

with hmp.open("projects/received", read_only=False) as cat:
    sim_ids = cat.import_package_multi("nancon_step1_minimal.hmp")
```

No function of the `hmp` namespace imports a package. The method takes `force=True` and
`as_project="name"`, like the options below.
:::

::::

The command verifies the SHA-256 digests first and changes nothing if one fails. It copies the
input files to `<project>/data/<role>/`, for example `data/dem/`, and rewrites the paths of the
stored configuration to point there. The run keeps its `sim_id`.

```{image} ../_static/figures/staircase/step1/watershed_id_card.webp
:alt: The watershed identity card of the run nancon_step1_minimal, drawn from the imported run.
```

The check that the import worked is to draw a figure from the imported run, as above. The
catchment card of step 1 must come out.

Two options cover the usual refusals:

- `--as NAME` gives the imported run another project name. It is needed to add a second run of
  the same origin project to a project that already holds one.
- `--force` replaces a run that has the same `sim_id`.

`hmp data import` reads the same package. It adds `--dry-run`, which validates the package and
writes nothing, and `--as` and `--force` too:

```bash
hmp data import nancon_step1_minimal.hmp --dry-run
```

```text
Dry-run OK. Archive would import sim a7c951a6-a958-4143-a095-60dda0946b6c
```

A package that holds several runs is written from Python with `export_package_multi`, and
`hmp catalog import` reads it. The command line writes one run per package.

## 6. Send the data cache as well

A package carries the inputs of one run. To hand over the cache of a whole workspace, archive
it:

```bash
hmp data archive data-cache.tar.zst --workspace .
hmp data restore data-cache.tar.zst --workspace ../other-workspace
```

The archive of the example 04 cache is 22.7 MB and took 11 s. `restore` unpacks it into
`<workspace>/data/imported` and checks the digests. It does not put the files back in
`data/<variable>/` and does not fill the index, so `hmp data ls` still reads
`(no cache found)` afterwards. The page {doc}`work-offline` says what to do with the files.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `Name what to export (see --list), or write 'all'. Example: hmp export <run> head --time 2002-10-15`, exit 2 | No variable after the run | Write `all` for a package or a description |
| `format = 'stac' describes the whole run, not a variable. Write variables = "all".` | A variable name with `stac`, `rocrate`, `prov` or `package` | Write `all` |
| `Reference 'run_x' not found. Run \`hmp catalog ls\` to list known runs.`, exit 10 | The name matches no run of the project | Check the name, and the folder you run from |
| `Project '<name>' already exists in this workspace. Use \`--as <new_name>\` to import under a different project name.`, exit 1 | A run of the same origin project is already in the receiving project | Add `--as NAME` |
| `Simulation '<sim_id>' already exists. Use force=True to overwrite.`, exit 1 | The run is already there. On the command line the flag is `--force` | Skip the import, or add `--force` to replace the run |
| `No archive at <path>`, exit 10 | The path is wrong | Check the path |
| `zstd decompress error: Unknown frame descriptor`, exit 1 | The file is not a package | Send the `.hmp` file, not a folder or an archive of another kind |
| `SHA-256 mismatch for <file>: expected <digest>, got <digest>` | The file was changed or damaged after it was written | Send it again |
| `audit emission failed for export` in Python | The catalog was opened for reading only | Open it with `read_only=False` |
| `hmp data ls` reads `(no cache found)` after `hmp data restore` | `restore` does not fill the index | Read {doc}`work-offline` |

## Next

- Give maps and tables to people who use a GIS: {doc}`hand-off-to-gis`.
- Remove a run and keep a proof that it was removed: {doc}`audit-and-purge`.
- The run folder and what each file holds: {doc}`read-the-results`.
- Every option of the commands: {doc}`../reference/cli/export`, {doc}`../reference/cli/catalog`
  and {doc}`../reference/cli/data`.
