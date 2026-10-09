# Set up your editor

A TOML editor can complete the keys of a HydroModPy file, show the description of a key
when you hover it, and underline a mistake before you run anything. It needs one thing: the
JSON Schema that HydroModPy publishes with this site. You point the editor at it with one
line at the top of the file.

```{hmp-task}
Task
: Get completion, hover help and underlined mistakes for a HydroModPy TOML file in your editor.

Time
: Five minutes, once.

Needs
: An editor that reads TOML through Taplo (VS Code with *Even Better TOML*, or any editor with a language server), and the address of the schema or a local copy.

Gives
: A file that is checked for names, types and choices as you type, and `taplo lint` for a terminal or a CI job.
```

## 1. Add the header

Put this line first in the file, before any key:

```toml
#:schema https://docs.hydromodpy.fr/main/_static/hydromodpy-schema.json

base_config = "step1_minimal.toml"

[flow]
flow_regime = "transient"
```

The line is a comment for TOML and for HydroModPy, so it changes nothing when the file
runs. [Taplo](https://taplo.tamasfe.dev/) reads it as a directive. A header directive can
only be preceded by other directives or by comments, and a file must carry one schema
directive at most.

The folder in the address is the version of this documentation. `main` follows the main
branch. Use the folder of the version you installed, as the version switcher of this site
names it, so the keys offered are the keys your version reads.

## 2. Use an editor that reads it

The schema is read by Taplo, the TOML toolkit behind most editor integrations.

- **VS Code.** Install the extension *Even Better TOML*. Open a file that carries the
  header. Keys complete as you type, a hover shows the description of the key, and an
  unknown key or a wrong value is underlined.
- **Any editor with a language server.** Run the Taplo language server (`taplo lsp stdio`).
  Helix, Neovim, Zed and others can start it for TOML files.
- **A terminal or a CI job.** `taplo lint step2_local_data.toml` checks the file against the
  schema named in its header and exits with an error when it does not fit.

To give the schema to many files without editing each one, write a `.taplo.toml` at the root
of the folder:

```toml
# not checked: configuration of the editor, not of HydroModPy
[[rule]]
include = ["**/*.toml"]

[rule.schema]
path = "https://docs.hydromodpy.fr/main/_static/hydromodpy-schema.json"
```

The `path` may also name a local copy of the schema, such as `./hydromodpy-schema.json`.
Write one with `hmp config schema --editor --out hydromodpy-schema.json`, or download the
file from the address above.

```{note}
`hmp config schema` exports the schema of the model, which lists every required key and does
not know the grammar of an overlay file. It is made for frontends. Do not give it to an
editor: pass `--editor` for the schema made for an editor.
```

## 3. What the schema checks

The schema reads one file at a time, as you wrote it. It checks:

- section and key names, so a typo is underlined;
- the type of a value, and the allowed values of a choice;
- the numeric bounds of a value written as a number;
- a quantity written as text, which must be a number followed by a unit, such as
  `'150 m'` or `'0.36 m/h'`;
- the forms of a file that extends another one: `base_config` at the top, `<key>__append`
  on a key that holds a list, and `<key>__delete = true` (see {doc}`inheritance`). The
  schema does not know `<key>__merge` yet, so an editor underlines it. `hmp config check`
  accepts it.

It does not ask for any key. A file may state only what it changes, and the file it extends
supplies the rest, so a missing key is not an error for the editor.

## 4. What only `hmp config check` checks

The schema cannot see the merged configuration or the data. Run the command before a run:

```bash
hmp config check step2_local_data.toml
```

It follows the `base_config` chain, merges the files, and validates the result with the
same code as `hmp run`. These checks stay with it:

| Check | Why the schema cannot do it |
|---|---|
| Keys that are required | An overlay file leaves them to its base file |
| The base file exists and the chain has no loop | The schema reads one file |
| A rule between two keys, such as a key that is required for one value of another | The schema describes each key alone |
| The unit of a quantity, and its bound after conversion | The schema checks the shape of the text, not the unit |
| The names of the exported variables and the time selectors | They depend on the processes the file turns on |
| That the files and the data named in the file exist | They live on your disk, not in the schema |

A mistake that passes the editor and fails here is expected. A mistake the editor
underlines is always worth a look.

## What the schema does not cover

The schema describes the files of a simulation, a calibration and an overview. The files of
the other workflow modes (`comparison`, `testbed` and `site_selection`), and the report
files, are read by their own models. Leave the header out of those files, or the editor will
underline sections it does not know.

Dates are read as text by the schema, whether you quote them or write a TOML date.

## How to check it worked

- Type a wrong key under `[flow]`, such as `flow_regme`. The editor underlines it.
- Type `flow_regime = "` and the editor offers `steady` and `transient`.
- `taplo lint step2_local_data.toml` exits 0 on a good file, and with an error on a file that
  does not fit the schema.
- `hmp config check step2_local_data.toml` prints `OK:` and the path. This is the check that
  counts, because it merges the chain.

## What can go wrong

| What you see | Cause | Fix |
|---|---|---|
| No completion, no underline | The `#:schema` line is not the first line, or something other than a directive or a comment precedes it. | Put it first, before any key. |
| Taplo reports a second schema | A file carries one schema directive at most. | Keep one. |
| The editor knows no key of a new version | The address names the `main` folder, which follows the main branch. | Use the folder of the version you installed, as the version switcher of this site names it. |
| The address answers 404, or the schema is the old one | The folder is not deployed yet. | Use a local copy: `hmp config schema --editor --out hydromodpy-schema.json`, and point `path` at it. |
| Every section of a comparison, testbed or report file is underlined | Those files are read by their own models. | Leave the header out of those files. |
| `[[export__merge]]` is underlined, and `hmp config check` accepts the file | The schema does not know `__merge` yet. | Ignore the underline, or use `__append` or a plain list. |
| A required key is not reported | An overlay file leaves required keys to its base file. | Run `hmp config check`, which merges the chain. |
| `hmp config schema` gives a schema that rejects overlay files | It exports the schema of the model, with every required key. It is made for frontends. | Do not give it to an editor. Use the published schema. |

## Where to go next

- {doc}`inheritance` for the rules of `base_config`, `__append`, `__delete` and `__merge`.
- {doc}`../reference/parameters/grammar` for the grammar of a file.
- {doc}`troubleshooting` for the messages of `hmp config check`.
