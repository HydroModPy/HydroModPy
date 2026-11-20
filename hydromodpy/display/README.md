# display

`display` draws. It takes a run that is already computed, or data that is already loaded, and writes PNG figures, HTML pages and the tables behind them. It never runs a solver and never writes into the storage of a run. It reads only `core` and `results`, and everything it reads from a run goes through `subject.py`.

A figure is a `FigureRequest` from `request.py`. It names a variable, a preset, a list of panels or a special figure. `render.py` expands it against `PRESETS`, draws each panel with a frame of `frames/` (map, series, section, xy, distribution, groups, table, volume) and then the overlays of `overlays.py`. A special figure is a function of `special/` for a case no frame expresses, and `request.SPECIALS` lists them.

`output.py` writes the files, stamps each PNG with the identity of the run and records the request in `figures/index.json`, so `hmp export <run> --regen figures` draws it again. A figure that cannot draw a run is refused with a sentence and never leaves a placeholder file. `tests/ports/test_figure.py` plays every preset and every drawable variable on the subjects of a frozen example.

The package page in the developer docs lists the modules and holds the import rules and where to add a frame, a variable or a preset.
