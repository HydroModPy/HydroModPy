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
- **A manifest**, `manifest.json`, written last. It lists the input files the configuration
  declared, each with its checksum, the output files, the period, the geometry and the scores.
  A run folder without a manifest is an incomplete run by construction.

A checksum is a short code computed from the content of a file. If one byte changes, the code
changes. A checksum that matches is a strong sign that the file is the one that was used.

## What the project keeps

At the root of a project, the {term}`lockfile` `hydromodpy.lock` pins what fed the runs: the
version of the code, the solver binaries with their checksums, the versions of the file formats,
and every cached input with its checksum and size. It is written after a
successful run when the project has a data cache. If the write fails, a warning says so and the
run is not lost.

The lockfile answers a wider question than the manifest of one run: in what state was the whole
data cache before the run?

## What you can ask for

| You want to know | You ask for | Command |
|---|---|---|
| What exactly was run? | The summary of the run: solver, status, duration, size of the grid, parameters, scores and the start of the configuration fingerprint. The frozen configuration and the provenance record are files of the run folder, which you can open. | `hmp catalog show <run>` |
| What differs between two runs? | The comparison of the two. | `hmp catalog diff <run A> <run B>` |
| Whether the data cache is still the one that was used | A check of the cache against the lockfile. | `hmp dev lock verify` |
| To replay a run with exactly the same data | A run that refuses any fresh download and stops on a checksum that does not match. | `hmp run --frozen <file>` |
| To rerun a stored run, changing one setting | A rerun from the stored configuration. | `hmp catalog rerun <run> --set path=value` |
| Whether the log of operations was altered | A check of its chain of hashes. | `hmp audit verify` |

The options of each command are in the {doc}`command reference <../reference/cli/index>`.

## What this does not prove

A record shows what was run. It does not show that the run was a good idea. Two identical records
mean two identical computations, and a correct computation can still rest on a poor assumption or
a poor dataset. For that, read {doc}`what-validated-means` and {doc}`where-the-data-come-from`.

A note on recorded data: the record contains the name of the machine and the user. Remove them
before you share a run folder outside your organisation if that matters to you.

## Where to go next

- {doc}`where-the-data-come-from`: the origin of each input.
- {doc}`../reference/cli/run`: `--frozen` runs from the cache, with no download.
- {doc}`glossary`: the terms of this page.
