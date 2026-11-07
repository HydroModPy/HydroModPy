# core/workspace

This folder answers: where does a project live, and what are the paths of a workspace? A workspace
holds several projects; the project folder is never written in a file, the loader sets it from where
the file sits.

## Modules, in the order a caller uses them

1. `config.py` is `WorkspaceConfig`. It resolves the workspace in four steps: explicit `[workspace]` keys, then `HMP_WORKSPACE`, then the scaffold `<workspace>/projects/<name>/`, then the project folder itself.
2. `workspace.py` is `WorkspaceLayout`, the runtime object built from it. The public `Workspace` is in `hydromodpy.project.accessors`.
3. `path_registry.py` is `WorkspacePathRegistry`, the canonical paths shared by runtime components.
4. `resolve.py` holds the lookups of the workspace root. `locate_workspace_root` is the best-effort lookup from a project directory. `find_workspace_root`, `find_data_workspace` and `find_workspace` serve the commands: they walk up from a folder, or read `-w` and `HMP_WORKSPACE`, and return `None` on a miss. They never exit, so the refusal stays in `cli/helpers.py`.
5. `workspace_toml.py` is `workspace.toml`, the metadata file at the root of a workspace (`WorkspaceToml`, `load_workspace_toml`, `write_workspace_toml`).
6. `exceptions.py` holds `WorkspaceError`.

## What other layers import from it

`results`, `project`, `config`, `cli`, `calibration`, `workflow` and `data`. `hydromodpy.core` exposes `Workspace`, `WorkspaceConfig` and `WorkspacePathRegistry` lazily.

## Where to add what

- A new folder under the workspace: `path_registry.py`.
- A new key of the workspace metadata: `workspace_toml.py`.
- A folder name inside a project: `core/state/layout.py`.

The layer rules are checked by `tests/unit/architecture/`.
