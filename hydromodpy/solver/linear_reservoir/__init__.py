"""The linear reservoir: one global flow model on the one-cell catchment mesh.

It solves ``ds/dt = R - s/tau`` exactly on every piece of constant rate the
run carries, from the state the steady variant of the model holds. See the
README of the folder for the model and ``options.py`` for its table.
"""
