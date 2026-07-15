"""Hydrographic-network accessors for :class:`hydromodpy.results.run.Run`.

Mixin that exposes the canonical hydrographic-network roles persisted with a
simulation (``reference``, ``generated``, ``simulated_active``) and their
geometric comparison helpers. Mixed into :class:`Run`; it assumes ``self``
has ``_sim_id`` and ``_catalog`` set by :meth:`Run.__init__`, and access to
``self.geographic`` (provided by :class:`RunGeographicMixin`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas as gpd


class RunHydrographicMixin:
    """Hydrographic-network accessors mixed into :class:`Run`."""

    def available_hydrographic_network_roles(self) -> list[str]:
        """Return the canonical hydrographic-network roles stored for this run."""
        from hydromodpy.spatial.geographic.core.hydrographic_network import (
            canonical_feature_name_for_role,
        )

        feature_names = set(self._catalog.list_geographic_features(self._sim_id))
        roles: list[str] = []
        for role in ("reference", "generated", "simulated_active"):
            feature_name = canonical_feature_name_for_role(role)
            if feature_name is not None and feature_name in feature_names:
                roles.append(role)
        return roles

    def has_hydrographic_network(self, role: str = "generated") -> bool:
        """Return true when the requested hydrographic-network role exists."""
        return role in self.available_hydrographic_network_roles()

    def hydrographic_network(self, role: str = "generated") -> gpd.GeoDataFrame:
        """Return one persisted hydrographic network by canonical role."""
        from hydromodpy.spatial.geographic.core.hydrographic_network import (
            canonical_feature_name_for_role,
        )

        feature_name = canonical_feature_name_for_role(role)
        if feature_name is None:
            raise ValueError(
                "Unknown hydrographic-network role. Expected one of: "
                "reference, generated, simulated_active."
            )
        try:
            return self.geographic(feature_name)
        except KeyError as exc:
            available = self.available_hydrographic_network_roles()
            available_str = ", ".join(available) if available else "none"
            raise KeyError(
                f"Hydrographic network role '{role}' is not available for sim {self._sim_id}. "
                f"Available roles: {available_str}."
            ) from exc

    def hydrographic_network_naming(self, role: str = "generated") -> dict[str, str | None]:
        """Return canonical naming hints for one hydrographic-network role."""
        from hydromodpy.spatial.geographic.core.hydrographic_network import (
            hydrographic_network_naming_contract,
        )

        contract = hydrographic_network_naming_contract(role)
        if contract.get("canonical_feature_name") is None:
            raise ValueError(
                "Unknown hydrographic-network role. Expected one of: "
                "reference, generated, simulated_active."
            )
        return contract

    def hydrographic_network_comparison(
        self,
        *,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        tolerance_m: float = 50.0,
    ):
        """Return one tolerance-based geometric comparison between two stored networks."""
        from hydromodpy.spatial.geographic.core.hydrographic_network_comparison import (
            compare_hydrographic_networks,
        )

        missing = [
            role
            for role in (reference_role, candidate_role)
            if not self.has_hydrographic_network(role)
        ]
        if missing:
            missing_str = ", ".join(missing)
            available = self.available_hydrographic_network_roles()
            available_str = ", ".join(available) if available else "none"
            raise ValueError(
                "Hydrographic-network comparison requires both requested roles to be present. "
                f"Missing: {missing_str}. Available roles for sim {self._sim_id}: {available_str}."
            )

        return compare_hydrographic_networks(
            self.hydrographic_network(reference_role),
            self.hydrographic_network(candidate_role),
            tolerance_m=tolerance_m,
        )

    def hydrographic_network_comparison_metrics(
        self,
        *,
        reference_role: str = "reference",
        candidate_role: str = "generated",
        tolerance_m: float = 50.0,
        **metadata,
    ) -> dict[str, object]:
        """Return one flat metrics record for the stored hydrographic-network comparison."""
        comparison = self.hydrographic_network_comparison(
            reference_role=reference_role,
            candidate_role=candidate_role,
            tolerance_m=tolerance_m,
        )
        return comparison.to_metrics_record(
            reference_role=reference_role,
            candidate_role=candidate_role,
            **metadata,
        )
