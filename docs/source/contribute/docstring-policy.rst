Docstring Policy
================

The API reference is generated from curated manifests. Navigation pages are
handwritten. Object pages come from docstrings. This split keeps the reference
stable for readers and cheap to maintain for developers.

What To Document
----------------

Document an object when it is one of these:

- a user entry point;
- a scientific component that can be called directly;
- a developer contract needed to extend the workflow engine;
- a configuration model that appears in TOML or JSON Schema.

Do not document every helper function. A private helper should stay private
unless it becomes part of a clear external workflow.

Docstring Shape
---------------

Use simple technical English. State what the object does before explaining how
it is implemented.

.. code-block:: python

   def run(config: str | Path, **kwargs: Any) -> Run | None:
       """Run a HydroModPy workflow from a TOML file.

       Parameters
       ----------
       config
           Path to a TOML file with a ``workflow`` field.
       **kwargs
           Runtime options forwarded to the selected workflow.

       Returns
       -------
       Run or None
           Persisted run object for simulation workflows. Other workflows may
           return their own summary type.

       Raises
       ------
       ConfigError
           Raised when the TOML file cannot be resolved or validated.
       """

For user and scientific objects, prefer these sections:

- ``Parameters`` for inputs that users can control.
- ``Returns`` for the concrete object or data shape.
- ``Raises`` for errors that a caller can handle.
- ``Examples`` for one short runnable pattern.
- ``See Also`` for nearby public objects.
- ``Notes`` only for scientific assumptions or important implementation limits.

Layer Rules
-----------

User docstrings should describe behaviour in workflow terms. Avoid pipeline
internals unless the user must know them.

Scientific docstrings should include units, array shape, coordinate convention,
solver assumptions, and numerical limits when they affect results.

Developer docstrings should name the contract and the expected caller. They can
mention internal state, but should stay short.

Canonical Imports
-----------------

Each documented symbol should have one canonical import path. Use that path in
the API manifest. Avoid documenting both a package-level lazy export and the
implementation class unless there is a clear reason.

Maintenance Rule
----------------

When adding a public object, update one manifest page and write the docstring.
Do not create a separate handwritten object page unless the object needs a
long tutorial. Tutorials belong in the user guide, scientific notes, or
capability gallery.
