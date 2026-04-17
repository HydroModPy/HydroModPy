"""Legacy compatibility outputs for flow adapters.

The modern simulation runtime keeps concrete solver instances in
``state.execution.models_by_run_id``. This module isolates the remaining
historical disk artifact used by older external tooling:
``results_<model>.pkl``.

Nothing here should be part of the canonical runtime contract. Callers must
opt in explicitly when they still need the historical pickle.
"""

from __future__ import annotations

import pickle
from collections.abc import Mapping
from pathlib import Path


def should_write_legacy_pre_run_pickle(
    flow_runtime_overrides: Mapping[str, object] | None,
) -> bool:
    """Return ``True`` only when one caller explicitly opts into legacy output."""
    return bool(
        isinstance(flow_runtime_overrides, Mapping)
        and flow_runtime_overrides.get("write_legacy_pre_run_pickle", False)
    )


def write_legacy_pre_run_pickle(workspace, model_name: str, model_modflow) -> None:
    """Write the historical ``results_<model>.pkl`` payload to disk."""
    pickle_path = (
        Path(workspace.simulations_folder)
        / model_name
        / f"results_{model_name}.pkl"
    )
    pickle_path.parent.mkdir(parents=True, exist_ok=True)
    with pickle_path.open("wb") as fh:
        pickle.dump(
            {
                "list_model_name": [model_name],
                "list_model_modflow": [model_modflow],
            },
            fh,
        )
