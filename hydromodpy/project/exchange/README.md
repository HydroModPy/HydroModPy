# `hydromodpy/project/exchange`

How a run travels between workspaces: publish a copy with the files it read, install
that copy elsewhere, replay it from its own bytes. It needs to see both the run
(`results`) and the data of a workspace (`data`), and no lower layer sees both, so
it sits here.

## Import rules

`exchange/` sits inside `hydromodpy/project`, which is above the layer matrix
(`tests/unit/architecture/layer_matrix.yaml`), so it may import any layer. It never imports
`Project` (`ImportedProject` is a result record, not the facade). It does not import
`launch/` or `dispatch/`. The CLI commands `hmp publish`, `hmp catalog import` and
`hmp project import` call into it, not the reverse.

## Modules, in the order a copy travels

| module | what it answers |
|---|---|
| `share.py` | what a published run needs to be installed elsewhere: `run_bundle` (the install index of a sealed run) and `inputs_of` (what `hmp publish --with inputs` passes along) |
| `install.py` | how a copy lands in a workspace: `install_index` (files, station rows, cache rows, sites; every conflict named before anything is written), `import_run` (`hmp catalog import`), `import_project` (`hmp project import`) |
| `replay.py` | how a published copy runs again from its own bytes: `published_copy_of`, `checked_index`, `input_files_by_role`, `replay_payload` (`ReplayInputError` when an input is missing or altered) |

## Tree

```
exchange/
  share.py     publish side: the install index of a run
  install.py   install side: files, rows and sites into a workspace
  replay.py    replay side: hmp run <copy>/config.toml --frozen
```

## Where to add what

| to add | where |
|---|---|
| a kind of file a published run carries | `share.py` (`run_bundle`) |
| a check or a conflict when installing | `install.py` (`install_index`); name it before any write |
| a new thing `hmp catalog import` or `hmp project import` brings in | `install.py` |
| a check on a copy before it is replayed | `replay.py` (`checked_index`) |
| the format of the install index itself | not here: `hydromodpy.core.payload` |
