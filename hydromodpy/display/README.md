# display

`display` draws. It takes a run that is already computed, or data that is already loaded, and writes PNG figures and HTML pages. It never runs a solver, never reads a raw solver file and never writes into the storage of a run, so everything a figure reads from a run goes through the public API of `results`. It reads only `core` and `results`, and it carries the figure port, because its registry `figure_registry.py` sits at the root of the package.

## The figure port

A figure receives its subject, the object `FigureSpec.subject` names: a `Run` (the default), a calibration `Session` or a `RunSet`. `unavailable_reason(subject)` returns `None` or the sentence that says why the subject cannot feed the figure, and then `render(subject, ax, **opts)` draws on the axes it gets and returns them, or raises `FigureNotApplicable` with a sentence for what only the data shows. `BaseFigure.plot` builds the figure, calls `render` and writes the PNG with its provenance.

A figure is a `BaseFigure` subclass of a public module of `figures/` that declares `name`, `spec`, `render` and `plot`. The `FigureSpec` holds the name, the title, the former names, the `kind`, the `required_fields`, `optional_fields` and `required_tables`, the default size and the subject. A need `spec` cannot express goes in an `unavailable_reason` override that calls the base first. A figure shows a quantity under the names of `results/field_registry.py`, and neither its name nor its title names a solver or a data provider.

A figure registers by membership. The generated table `figure_table.py` lists every figure class under its `spec.name`, and `figures` is the `PluginRegistry` built from it, with no entry-point group. After adding or renaming a figure, run `python -m tools.figure_table`, because a test regenerates the table in memory and fails on a stale file.

A name of `[display].figures`, `hmp show <run> --figure <name>` or `run.figure("<name>")` that no figure carries is refused with the names registered, and a renamed figure keeps its old name in `former_names`. A figure that cannot draw a run is refused or skipped with its sentence on every surface and never writes a placeholder PNG. `tests/ports/test_figure.py` plays every figure the registry serves on the subjects of a frozen example, and any exception other than `FigureNotApplicable` is a defect.

The page of the package in the developer docs gives the rules a user can rely on, the import rules, the flow of a render and where to add what.
