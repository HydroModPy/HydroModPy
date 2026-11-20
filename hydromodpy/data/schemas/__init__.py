"""Input-data contracts expressed as pandera schemas.

Each submodule exposes a pandera :class:`DataFrameSchema` and a
``validate()`` helper that wraps pandera's validation error into
:class:`hydromodpy.core.exceptions.DataContractViolation`.

Spec reference: ``architecture_cible/03_data_contracts.md``.
"""
