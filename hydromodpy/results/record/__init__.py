"""The record of a run: the seal, its identity, its checks and its label.

The record builds the seal in memory and writes it without the index. The
identity block, the checks and the request identity sit beside it, and the
lineage block is :mod:`hydromodpy.schema.lineage`. Import a name from the module
that defines it: this package re-exports nothing.
"""
