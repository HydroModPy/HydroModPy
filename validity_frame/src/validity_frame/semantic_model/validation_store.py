# validity_frame/src/validity_frame/semantic_model/validation_store.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UncertaintyDescriptors:
    """Incer = {m_j, s_j} extrait du HCDM."""
    log_mean: dict[str, float] = field(default_factory=dict)
    # m_j : log-moyenne par type de roche
    log_std: dict[str, float] = field(default_factory=dict)
    # s_j : log-écart type (variabilité naturelle)


@dataclass
class ValidationStore:
    """VA = ⟨X_r, P_r, τ, Val, Incer⟩"""
    X_r: dict[str, Any] = field(default_factory=dict)
    # résultats de simulation
    P_r: dict[str, Any] = field(default_factory=dict)
    # ensembles de paramètres valides
    tau: float | None = None
    # seuil d'acceptation τ
    val: float | str | None = None
    # valeur de la métrique de validation (ex: R²)
    metric_name: str = "R2"
    # nom de la métrique (R2, NSE, RMSE...)
    incer: UncertaintyDescriptors = field(default_factory=UncertaintyDescriptors)

    def compute_delta(
        self,
        poi_r: dict[str, Any],
        poi_s: dict[str, Any],
        distance_fn=None,
    ) -> float | None:
        """Δ = d(PoI_r, PoI_s)"""
        if distance_fn is not None:
            return distance_fn(poi_r, poi_s)
        common = set(poi_r) & set(poi_s)
        if not common:
            return None
        return sum(abs(float(poi_r[k]) - float(poi_s[k])) for k in common) / len(common)