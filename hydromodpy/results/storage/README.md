# `hydromodpy/results/storage`

What a run directory holds, under which names, and how its files are written. `contract.py` is
the place to look for a name: `CERTIFIED_RUN_ENTRIES` lists what the seal inventories, and
`UNSEALED_RUN_ENTRIES` what it never does, which is derived, mutable, diagnostic or machine
state. A new file enters `contract.py` first, then `tests/unit/results/test_run_layout_contract.py`.
The seal is written in one order: the CRS in WKT2, the attributes of `fields.zarr` from the
`Identity`, the value digests, the copy of the sealed mesh, the class of a replay, the record of
the run, then `README.md`. A run that reads a product of the store copies the mesh under `mesh/`
when its engine caches one, and `final_state/` holds the last head and stages in float64, which
a restart and the next window read before the last step of `fields.zarr`. `profile.json` sits
outside the seal and the identity, because it describes one machine. `kept.py` gives the level
of a run and what that level keeps: a kept calibration trial is a research run, keeps no figure
and no export, and leaves `purged.json` when `gc` removes fields older than its policy, a file
outside the seal like the outcome. `declared.py` holds what a backend may write: a field or
table its `writes` does not declare, and a simulated series the registry does not describe, are
refused. The table below gives the module of each part, and its
answers column is the first line of the module docstring.

| module | answers |
|---|---|
| `array_fingerprint.py` | Input provenance fingerprinting for simulation reproducibility. |
| `arrow_tables.py` | Build the Arrow tables of the Parquet payloads of a run. |
| `attempt.py` | The attempt protocol: who may work in a run directory, and how it ends. |
| `contract.py` | Result-storage layout contract: what one run and one session directory hold. |
| `declared.py` | What a backend may write into the store of a run, and what is refused. |
| `diagnostics.py` | Diagnostics for the project result-storage layout. |
| `digests.py` | Digests and sizes of the files a run reads or writes. |
| `final_state.py` | The last state of a run, in double precision, for the run that starts from it. |
| `geo_metadata.py` | Geographic facts a run states about itself, and how they are typed. |
| `json_io.py` | Atomic JSON documents of a run, a session, a plan or a publication. |
| `kept.py` | What a run keeps of its solver outputs, and the witness of a purged trial. |
| `licence.py` | The licence a run may state, derived from the inputs it read. |
| `parquet_io.py` | Atomic pyarrow Parquet writer with canonical V1 options forced. |
| `parquet_schemas.py` | PyArrow schemas for every per-simulation Parquet file. |
| `prior_state.py` | Read an earlier run as the state a new run starts from. |
| `run_facts.py` | The facts a run accumulates about itself before its seal. |
| `run_log.py` | The log of one attempt: `<run>/logs/run.log`, and the tail the outcome carries. |
| `run_profile.py` | `profile.json`: where a run spent its time and memory, attempt by attempt. |
| `run_store.py` | The store of one run: its Zarr arrays, its Parquet tables and its facts. |
| `scratch.py` | The solver scratch of an attempt: what leaves it at the end of a run, and how. |
| `sealing.py` | The seal of a completed run, built from its store and written by it. |
| `soil_tables.py` | What a soil-reservoir run writes about its columns. |
| `udunits.py` | The one spelling of a unit in a stored table: udunits, as the field registry writes it. |
