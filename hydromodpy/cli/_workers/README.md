# `hydromodpy/cli/_workers`

The work behind a verb that `hydromodpy._api` does not offer. A command module
parses its arguments, calls one function here and formats what it returns. A
worker raises an exception and never exits: the command maps it to an exit code.

| file | serves |
|---|---|
| `catalog.py` | `hmp catalog` reads (`ls`, `show`, `query`, `point`, `diff`, `rank`, `reindex`, `watch`), the counts `hmp doctor` prints, and what several verbs share: `project_root_at`, `reindex_if_indexed` after a verb changed runs, `remove_for_good` (trash then purge, the name stays taken) and `path_size` |
| `data.py` | `hmp data`: list, request, check, add, remove, prune, archive and restore the input cache of a workspace |
| `lock.py` | `hmp lock update` and `hmp lock verify`: the lockfile of a project against the cache it pins |
| `example.py` | `hmp example list` and `show`, and the manifest `hmp dev examples manifest` writes |
| `privacy.py` | `hmp privacy purge` and `verify`: a run removed for good, with its certificate |
| `project.py` | `hmp project new`, `list` and `delete`, and the root of a `[sites]` project |
| `viz.py` | `hmp viz show` and `list`, and the figures `hmp export --regen` draws again |
| `workspace.py` | `hmp workspace init`, `list` and `clean` |

A function a Python user needs too belongs in `hydromodpy._api` or in its
domain package, not here.
