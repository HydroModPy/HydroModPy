hmp viz
=======

The :command:`hmp viz` family groups the interactive visualization
helpers. Today the family hosts a single action, :command:`hmp viz serve`.
The flat :command:`hmp display` (one-shot figure render) and
:command:`hmp report` (HTML calibration report) verbs will be folded
into this family in a later interface iteration.

serve
-----

Synopsis: ``hmp viz serve [--port <port>] [--workspace <path>]``

Launch the Streamlit-based configuration and inspection UI for the
active workspace. The browser tab opens a TOML wizard, a catalog
browser, and a figure preview panel; it is the recommended entry point
for non-CLI users who want to explore a workspace without writing
Python.

Example::

   hmp viz serve --port 8501
