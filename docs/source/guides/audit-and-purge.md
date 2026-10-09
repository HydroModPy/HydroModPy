# Audit and purge

```{hmp-task}
Task
: Read what happened to the runs of a project, and remove one run for good with a certificate.

Time
: Two minutes.

Needs
: A project with a catalog. A run to remove, for the second part.

Gives
: The list of events, a check that the log is intact, a purge certificate.
```

Every project keeps an audit log of what was done to its runs: runs sealed, exports written,
packages imported, runs deleted. The log is a chain of hashes, so an edited row shows. When a
run must disappear, `hmp privacy purge` deletes it and writes a certificate that says which
run, when, who and why.

Both are command-line tools. The Python API has no function for them.

## 1. Read the log

```bash
hmp audit list --limit 5
```

The command prints a table of 13 columns, one row per event, newest first. The columns are
`event_id`, `seq`, `occurred_at`, `actor`, `actor_kind`, `event_type`, `sim_id`, `project`,
`payload`, `git_commit`, `hostname`, `prev_hash` and `chain_hash`. The lines are long. These
columns are enough to read it:

```text
 seq                      occurred_at      event_type      sim   payload
  13 2026-10-09 03:11:27.036347+02:00       sim.purge cc3b3c7f   {"reason":"data withdrawn by the provider","remove_storage":true,"sha256_snapshot":"62a0d5…"}
  12 2026-10-09 03:11:26.999988+02:00 sim.purge.begin cc3b3c7f   {"reason":"data withdrawn by the provider","remove_storage":true,"sha256_snapshot":"62a0d5…"}
  11 2026-10-09 03:11:21.337675+02:00    export.write cc3b3c7f   {"kind":"package","rel_path":"share/nancon_step2_local/nancon_step2_local.hmp"}
  10 2026-10-09 03:11:21.293003+02:00          export cc3b3c7f   {}
   9 2026-10-09 03:06:42.790914+02:00          import     None   {}
```

`--limit N` keeps the newest N rows. The default is 50. `--since 2026-10-01` keeps the rows from
that date or time on. The event types seen on a project are `sim.finalize` (a run sealed),
`export` and `export.write` (a command, then each file it wrote), `import`, `sim.purge.begin`,
`sim.delete` and `sim.purge`, and `migrate` when the index schema was upgraded.

The log of a project is in its own index: `.hmp/index.duckdb`. A workspace has one log per
project. Give the project folder with `--workspace`, or run the command from it.

## 2. Check that the log is intact

```bash
hmp audit verify
```

```text
audit_log hash chain verifies
```

Each row stores the hash of the row before it. The command replays the chain from the first
row and exits 0 when every link holds. A row that was edited breaks the chain: after one
`actor` value was changed in a copy of a project, the command printed
`audit_log hash chain verification FAILED` and exited 14. `--strict` gives the same message and
the same exit code.

The check does not protect the file. Anyone who can write `.hmp/index.duckdb` can rebuild the
log, and the commands of section 5 do so.

## 3. Remove a run and keep a proof

First decide if the removal must be final. `hmp catalog delete <run>` moves a run to the trash
and can be undone with `hmp catalog restore`. `hmp privacy purge` cannot be undone.

```bash
hmp privacy purge nancon_step2_local --reason "data withdrawn by the provider" -y
```

```text
Purged simulation cc3b3c7f-1fdb-433c-9cb0-4582ddf5d632
  removed: /…/projects/received/runs/nancon_step2_local
Certificate: /…/.hmp/purge_certificates/cc3b3c7f-1fdb-433c-9cb0-4582ddf5d632.json
```

The reference is a name, a `sim_id` or a unique prefix of it. Without `-y` the command asks
`Purge simulation 'REF'? [y/N]`. In a script, without a terminal, it refuses and exits 14:
`Refusing to purge without -y in non-interactive mode.`

The purge removes:

- the folder `runs/<name>/`: fields, tables, figures, the seal;
- the rows of the run in the index;
- the entries of the geographic cache that no remaining run uses.

It writes the certificate in `.hmp/purge_certificates/<sim_id>.json` at the root of the
workspace, with permissions `0600`. The certificate holds `sim_id`, `timestamp_utc`, `operator`,
`reason` and `sha256_snapshot`. The last one is the SHA-256 digest of the row of the run as it
was before the purge: its name, configuration hash and snapshot, dates and geographic
fingerprint. The audit log gets three events, `sim.purge.begin`, `sim.delete` and `sim.purge`,
with the reason and the same digest.

`--archive-pii` also writes `<sim_id>.pii.json` beside the certificate, also `0600`. It holds the
same row in full, with the configuration snapshot and the list of removed paths. Keep it only if
you are allowed to keep it.

The purge does not remove:

- the files you exported: `share/<run>/`, including any `.hmp` package;
- the input files an import copied to `data/<role>/`;
- any copy somewhere else.

Delete them yourself, and look in the folders you shared.

## 4. Check a certificate

```bash
hmp privacy verify .hmp/purge_certificates/cc3b3c7f-1fdb-433c-9cb0-4582ddf5d632.json --strict
```

```text
OK: certificate /…/cc3b3c7f-1fdb-433c-9cb0-4582ddf5d632.json verifies
  sim_id      : cc3b3c7f-1fdb-433c-9cb0-4582ddf5d632
  timestamp   : 2026-10-09T01:11:27.071062+00:00
  operator    : bb
  sha256      : 62a0d5453c911ec7...
```

The command checks that the file is a JSON object with the five fields, that
`sha256_snapshot` is 64 hexadecimal characters, and, with `--strict`, that the permissions are
`0600`. It does not look at the project. It does not prove that the run is gone. To show that, run
`hmp catalog ls` in the project, and `hmp audit list` for the `sim.purge` event of the `sim_id`.

## 5. Keep the log

The audit log lives in the index, and the index is rebuilt from the run folders. What no run
folder carries is lost in the rebuild. `hmp catalog reindex` says it in its help: the audit log
and its hash chain are lost, and a fresh chain starts. The deletion tombstones are lost with
them. `hmp workspace clean --results` deletes the index itself. The certificates are plain files
and stay.

Copy `.hmp/index.duckdb` to a safe place when the log matters, before you reindex or clean.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `No catalog at <folder>`, exit 10 | The folder is not a project, or it has no run yet | Give the project folder with `--workspace`, not the workspace root |
| ``Reference 'x' not found. Run `hmp catalog ls` to list known runs.``, exit 10 | The name matches no run | Check the name with `hmp catalog ls` |
| `Refusing to purge without -y in non-interactive mode.`, exit 14 | No terminal, and no `-y` | Add `-y` once you are sure |
| `audit_log hash chain verification FAILED`, exit 14 | A row was edited, or a row was removed from the middle of the log | Restore the saved copy of the index |
| `audit_log hash chain verifies` but the old events are gone | The index was rebuilt: `hmp catalog reindex` starts a new chain | Keep a copy of `.hmp/index.duckdb` before a rebuild |
| `Certificate missing required fields: sim_id, timestamp_utc, operator, reason, sha256_snapshot`, exit 14 | The file is not a certificate of this command | Check the path |
| `certificate permissions 0o644 != 0o600`, exit 14, with `--strict` | The certificate was copied with other permissions | `chmod 600` the file |
| `Certificate not found: <path>`, exit 10 | The path is wrong | Certificates are in `.hmp/purge_certificates/` at the workspace root |
| The purged data is still on disk | The purge covers `runs/<name>/` only | Remove `share/<run>/`, copied inputs and sent files by hand |

## Next

- Give a run away before you remove it: {doc}`share-a-run`.
- Trash and restore runs: {doc}`clean-and-reindex-runs`.
- Every option of the commands: {doc}`../reference/cli/audit` and {doc}`../reference/cli/privacy`.
- The exit codes: {doc}`../reference/cli/exit-codes`.
