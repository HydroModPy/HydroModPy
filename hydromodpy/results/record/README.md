# `hydromodpy/results/record`

The record of one run: the seal it writes, the value digests
and the class of a replay. `manifest.json` closes the run, at `manifest_version` 4 and
`profile = "run"`, on the common seal of `hydromodpy/schema/seal.py`, and the seal of a job is
the other profile of that document. A seal weighs 24 to 36 kB on the frozen runs of the
references, of which 14 to 19 kB are value digests, one per Zarr array and per column of a
quantity, taken under the rule `values/1`. A field rounded for storage is hashed in double
precision before the rounding of 2^-17, so `bit` covers the values as computed. A seal of the
2.0.0 reads through `forms.py`, in memory and never rewritten, and a seal of a pre-release is
refused with its sentence. A replay compares its digests with the seal of its source and writes
`bit` or `deviation`, with `max_abs` and `rel_l2` of the whole field for each key that differs.
This folder reads `core`, `schema` and `results`, and nothing above `results`.
The answers column below is the first line of each module docstring.

| module | answers |
|---|---|
| `checks.py` | The `checks` block of a seal: the facts a label is derived from. |
| `forms.py` | The forms of the 2.0.0, converted in memory when a reader meets them. |
| `label.py` | The identity block a derived file of a run carries, and the label of the day. |
| `manifest.py` | The run manifest: the schema of the seal and its reader. |
| `record.py` | The run record: the seal of a run, built in memory and written without the index. |
| `replay_class.py` | The class of a replay: whether it reproduced the sealed values, and by how much. |
| `request_identity.py` | The two fingerprints of a run: what it asks, and what computes it. |
| `values.py` | The value digests of a run, taken at the seal or recomputed from the disk. |
