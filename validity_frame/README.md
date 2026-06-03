Validity Frame Package
======================

This package provides a small, reusable validity frame that stays outside of
other projects. It is designed to be installed once and imported anywhere
without rewriting the validation logic.

What this package gives you
---------------------------

- a direct Python API: ``ValidityFrame``
- a helper to load a frame automatically from entry points:
	``create_validity_frame()``
- a minimal default implementation that you can extend or replace

What "minimal skeleton" means
------------------------------

It means the smallest working file structure needed to start the package,
install it, and extend it later. It includes only the essential files:
packaging metadata, a Python module, tests, and a short README.

Local editable installation:

```bash
pip install -e validity_frame
```

Minimal usage:

```python
from validity_frame import ValidityFrame

vf = ValidityFrame(tolerant=True)
vf.verify(state, steps)
```

The package does not depend on other frameworks and only expects compatible
objects through duck-typing.

Automatic loading with entry points
-----------------------------------

The package registers a default entry point named ``default`` in the
``validity_frame.frames`` group. You can load it with:

```python
from validity_frame import create_validity_frame

vf = create_validity_frame(tolerant=True)
vf.verify(state, steps)
```

If you later publish another implementation, you can register it in the same
entry-point group and load it by name.

Example of a custom entry point in another package
--------------------------------------------------

```toml
[project.entry-points."validity_frame.frames"]
my_custom_frame = "other_package.module:MyValidityFrame"
```

Then load it with:

```python
from validity_frame import create_validity_frame

vf = create_validity_frame("my_custom_frame", tolerant=False)
```

Sequence diagram
----------------

An executable sequence diagram showing how the auto-capture integration
operates is included in the package docs:

- `validity_frame/docs/validity_frame_runtime_sequence.puml` — shows
	adapter/entry-point resolution, collector start/end, probe collection,
	and how the runner writes the capture artifacts.

Render the diagram with PlantUML or view the original in the main
project docs at `docs/source/architecture/process/diagrams/validity_frame_runtime_sequence.puml`.
