# validity_frame/src/validity_frame/semantic_model/knowledge_record.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .context_model import ContextModel
from .expert import ExpertAnnotation, ExpertVerdict
from .meta_model import InfluenceFactors, ModelStructure, PropertiesOfInterest
from .validation_store import ValidationStore
from .validity_domain import ValidityDomain


class ValidationDecision(str, Enum):
    CVF = "CVF"  # Confirmed Validity Frame    (Δ ≤ τ)
    INCVF = "INCVF"  # Invalidated CVF             (Δ > τ)
    PENDING = "PENDING"


@dataclass
class FidelityLevel:
    """f(m) = P_0 ∧ P_1 ∧ P_2"""

    P0: bool = False  # observations expérimentales disponibles
    P1: bool = False  # résultats de simulation disponibles
    P2: bool = False  # jugement expert fourni

    def global_fidelity(self) -> bool:
        return self.P0 and self.P1 and self.P2


@dataclass
class ExecutionKnowledgeRecord:
    """Instance MSVF complète pour une exécution."""

    run_id: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # SPEC_exe — AutoCaptureSnapshot (code existant, non modifié)
    spec_exe: Any = None

    # Couche sémantique — remplie par l'utilisateur via TOML
    model_structure: ModelStructure | None = None  # SM
    properties_of_interest: PropertiesOfInterest | None = None  # Π_M
    influence_factors: InfluenceFactors | None = None  # Γ_M
    context: ContextModel | None = None  # CM
    validity_domain: ValidityDomain | None = None  # ZM

    # Résultats et validation — remplis par l'adapter
    validation_store: ValidationStore | None = None  # VA

    # Décision automatique
    decision: ValidationDecision = ValidationDecision.PENDING
    delta: float | None = None  # Δ = d(PoI_r, PoI_s)

    # Jugement expert — humain
    expert_annotation: ExpertAnnotation | None = None  # α_expert

    # Niveaux de fidélité
    fidelity: FidelityLevel = field(default_factory=FidelityLevel)

    # Provenance
    source_adapter: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def make_decision(self) -> ValidationDecision:
        """Decision(Δ, τ) → CVF si Δ ≤ τ, INCVF sinon."""
        va = self.validation_store
        if va is None or self.delta is None or va.tau is None:
            self.decision = ValidationDecision.PENDING
            return self.decision
        self.decision = ValidationDecision.CVF if self.delta <= va.tau else ValidationDecision.INCVF
        return self.decision

    def apply_expert(self, annotation: ExpertAnnotation) -> None:
        """Applique le jugement expert (P_2)."""
        self.expert_annotation = annotation
        self.fidelity.P2 = True
        if annotation.verdict == ExpertVerdict.REJECT:
            self.decision = ValidationDecision.INCVF
        elif annotation.verdict == ExpertVerdict.ACCEPT:
            self.decision = ValidationDecision.CVF
