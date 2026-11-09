"""The shapes HydroModPy writes for a reader outside this process.

The JSON Schema of the configuration (``config_schema.py``), the documents of
a run, a job and a capability, the register of changes, and the phrase of each
code a check of a configuration gives (``phrases.toml``). Every function that
reads the configuration takes the root model as its first argument, so this
package never imports ``hydromodpy.config``. Import a name from its module:
this package re-exports nothing.
"""
