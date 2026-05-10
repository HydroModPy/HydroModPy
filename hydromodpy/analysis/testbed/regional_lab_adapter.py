"""Projection helpers for the regional-lab testbed profile."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.config import TestbedVariantConfig
from hydromodpy.analysis.testbed.contracts import run_testbed_child_workflow
from hydromodpy.analysis.testbed.regional_lab_types import RegionalLabPlannedCase
from hydromodpy.analysis.testbed.runtime import TestbedPlannedCase


@dataclass(frozen=True)
class RegionalLabTestbedCase:
    """Testbed-style projection of one regional-lab planned case.

    A regional lab may mix simulation and comparison recipes in one campaign,
    while a standalone generic testbed has one runner for all variants. The
    projection therefore keeps both the testbed variant and the per-case runner.
    """

    case: TestbedPlannedCase
    runner: str
    regional_case_id: str
    recipe_id: str
    site_id: str

    @property
    def config_path(self) -> Path | None:
        """Return the delegated child config path."""
        return self.case.config_path

    @property
    def variant_id(self) -> str:
        """Return the testbed variant identifier."""
        return self.case.variant.id

    def to_mapping(self) -> dict[str, Any]:
        """Serialize the projection with testbed field names."""
        payload = self.case.to_mapping()
        payload.update(
            {
                "runner": self.runner,
                "regional_case_id": self.regional_case_id,
                "recipe_id": self.recipe_id,
                "site_id": self.site_id,
            }
        )
        return payload


def regional_case_to_testbed_case(case: RegionalLabPlannedCase) -> RegionalLabTestbedCase:
    """Project one regional-lab planned case onto the testbed case vocabulary."""
    site_label = case.site.site_label or case.site.site_id
    return RegionalLabTestbedCase(
        case=TestbedPlannedCase(
            variant=TestbedVariantConfig(
                id=case.case_id,
                label=f"{case.recipe_label} / {site_label}",
                axis=case.recipe_id,
                enabled=True,
                overlay={},
            ),
            config_path=case.config_path,
            status="planned",
        ),
        runner=case.launcher,
        regional_case_id=case.case_id,
        recipe_id=case.recipe_id,
        site_id=case.site.site_id,
    )


def regional_plan_to_testbed_cases(
    planned_cases: Sequence[RegionalLabPlannedCase],
) -> list[RegionalLabTestbedCase]:
    """Project a regional-lab plan to testbed-style planned cases."""
    return [regional_case_to_testbed_case(case) for case in planned_cases]


def run_case_with_testbed_provider(
    case: RegionalLabPlannedCase,
    *,
    no_display: bool = False,
) -> str:
    """Run one regional-lab planned case through the testbed runner provider."""
    testbed_case = regional_case_to_testbed_case(case)
    if testbed_case.config_path is None:
        return "failed"

    try:
        run_testbed_child_workflow(
            runner_type=testbed_case.runner,
            config_path=testbed_case.config_path,
            no_display=no_display,
        )
    except Exception:
        return "failed"
    return "ok"


__all__ = [
    "RegionalLabTestbedCase",
    "regional_case_to_testbed_case",
    "regional_plan_to_testbed_cases",
    "run_case_with_testbed_provider",
]
