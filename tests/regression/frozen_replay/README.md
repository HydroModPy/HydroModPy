# Frozen replay

`v2.1/current/` holds `tri.toml` and the run `runs/tri/` of the transient island on 434
gmsh triangles, solved by MODFLOW 6 with XT3D off over three months. It weighs about
380 kB. `v2.1/expected.json` holds its size, the digest of the folder and the value
digests of its seal.

`python -m tools.freeze_replay_run --out tests/regression/frozen_replay/v2.1 --work <folder>`
writes both. The host, the user and the local folders are replaced in the files that
name them, and the sealed digests are written again, so `seal_problems` stays empty.

`test_the_frozen_mf6_run_replays.py` checks the digest, the size, the seal and the
absence of any home folder. It then replays a copy of the run with `hmp replay` and
asks for the class `bit` on the `float64` basis, once with gmsh made unimportable,
because the replay reads the mesh sealed in the run.

The folder `v2.1/` is never edited by hand. The weekly job replays it on a second
processor, and `HMP_REPLAY_REPORT` names the file where the test writes the class and
the gaps it measured. The folder is written again after the version moves to 2.1.0.
