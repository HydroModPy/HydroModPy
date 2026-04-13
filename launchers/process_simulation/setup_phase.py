"""Setup phase — re-exports from ``hydromodpy.workflow.steps.setup``.

This module is kept for backward compatibility.  All implementation has
moved to :mod:`hydromodpy.workflow.steps.setup`.
"""

from hydromodpy.workflow.steps.setup import (  # noqa: F401
    build_geographic_runtime,
    collect_requested_support_ids,
    support_provider_names,
    resolve_support_configs,
    flow_requires_spatial_support,
    augment_runtime_zone_ids,
    validate_domain_support_contract,
    build_domain_spatial_supports,
    run_setup,
    step_setup,
)
