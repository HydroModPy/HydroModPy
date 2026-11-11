# Can I check what was run?

Yes. A result of HydroModPy is not only a map. It comes with the record of what produced it, and
that record can be read without the person who made the run. This page lists what is kept, and
what you can ask for when you receive a result. The word for this record is
{term}`provenance`.

## What a run keeps

Every finished run has its own folder. In it you find:

- **The configuration that ran.** A frozen copy of the TOML file, not the file as it is today.
  The run is stored with a fingerprint of that configuration, so two runs can be told apart or
  matched.
- **A provenance record**, `provenance.json`. It names the version of HydroModPy, the commit of
  the code it came from, the version of Python, the machine, the packages installed, and the
  solver with its version and the SHA-256 checksum of its binary.
- **The inputs it read**, `inputs.json`: one entry per dataset, downloaded or yours, with the
  provider, the product and its version, the full request (extent, period, stations), the
  date of the download, the checksum and the licence.
- **A manifest**, `manifest.json`, written last. It names the catchment, lists the output
  files, the period, the geometry, the scores with the window they were computed on, and the
  checks of the run (water budget, convergence). A run folder
  without a manifest is an incomplete run by construction; its `outcome.json` says how it
  ended.
- **A `README.md`**, generated from the manifest: the same facts in words, the {term}`run label`
  of the day, and the checksum of the manifest it summarizes.

A checksum is a short code computed from the content of a file. If one byte changes, the code
changes. A checksum that matches is a strong sign that the file is the one that was used.

## What the project keeps

At the root of a project, the {term}`lockfile` `hydromodpy.lock` pins what fed the runs: the
version of the code, and every cached input with its source, licence, checksum and size, read
from the sidecar that sits next to each file. The files you provide yourself, under `inputs/`,
are listed too. You write it with `hmp data lock`, and a launch of many cases writes it once the
data are fetched, not every run. Each run records the solver binary it used, with its checksum.

The lockfile answers a wider question than the manifest of one run: in what state was the whole
data cache before the run?

## What you can ask for

| You want to know | You ask for | Command |
|---|---|---|
| What exactly was run? | The summary of the run: solver, status, duration, size of the grid, parameters, scores and the start of the configuration fingerprint. The frozen configuration and the provenance record are files of the run folder, which you can open. | `hmp show <run>` |
| What differs between two runs? | The comparison of the two. | `hmp diff <run A> <run B>` |
| Whether the data cache is still the one that was used | A check of the cache against the lockfile. | `hmp data lock --check` |
| To replay a stored run with exactly the same data and settings | A run that pins each input at the digest of the seal and refuses an input that moved before anything runs. The replay is classed `bit` or `deviation`, with the size of each gap, and `--strict` refuses a gap before the seal. For a bare name outside the project, or for a copy, name the project with `-w <project>`. | `hmp replay <run>` |
| To replay a project file on its pinned data | A run that refuses any fresh download and stops on a checksum that does not match the lockfile. | `hmp run --frozen <file>` |
| To rerun a stored run, changing one setting | A rerun from the stored configuration. A default that moved since gets a warning and a line in the lineage of the new run. | `hmp catalog rerun <run> --set path=value` |
| To hand a run to someone | A copy that stands alone: the results, the final state, the inputs the run read, the sealed mesh, the README, the frozen configuration, the provenance with the machine and the user removed, the checksum of every file, and a `.zenodo.json`. `--without results` or `--without inputs` leaves a part out. A run that did not replay bit for bit is refused. | `hmp publish <run> --to <folder>` |
| To hand a run and its data to a colleague, who reruns it | The default copy, with every file the run read, which their import installs in their `data/`. | `hmp publish <run> --to sim.tar --container tar`, then `hmp catalog import sim.tar` |
| Whether a copy you received is intact | A check of every file of the copy against the checksums it carries. | `hmp publish --verify <folder>` |

The options of each command are in the {doc}`command reference <../reference/cli/index>`.

## What this does not prove

A record shows what was run. It does not show that the run was a good idea. Two identical records
mean two identical computations, and a correct computation can still rest on a poor assumption or
a poor dataset. For that, read {doc}`what-validated-means` and {doc}`where-the-data-come-from`.

A note on recorded data: the record contains the name of the machine and the user. `hmp publish`
removes them from the copy it writes. A run folder copied by hand still carries them.

## Where to go next

- {doc}`where-the-data-come-from`: the origin of each input.
- {doc}`../reference/cli/run`: `--frozen` runs from the cache, with no download.
- {doc}`glossary`: the terms of this page.
