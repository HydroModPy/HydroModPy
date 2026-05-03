"""Site filtering and case planning for the regional-lab launcher family."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from hydromodpy.analysis.batch.batch_catalog import (
    _current_platform_tokens,
    _normalize_platform_token,
    _normalize_required_field_names,
)
from hydromodpy.analysis.batch.batch_types import (
    RegionalLabPlannedCase,
    RegionalLabSiteRecord,
    RegionalLabSkippedCase,
    _merge_tags,
    _normalize_text,
)
from hydromodpy.analysis.batch.config import (
    RegionalLabClusterRuleConfig,
    RegionalLabConfig,
    RegionalLabRecipeConfig,
    RegionalLabSelectionConfig,
)


def _matches_text_filter(value: str | None, allowed: tuple[str, ...]) -> bool:
    """Return whether one optional text value matches one allowed-text filter."""
    if not allowed:
        return True
    normalized_value = "" if value is None else value.lower()
    return normalized_value in {item.lower() for item in allowed}


def _site_matches_selection(
    site: RegionalLabSiteRecord,
    *,
    selection: RegionalLabSelectionConfig,
) -> bool:
    """Return whether one site matches a set of selection filters."""
    if not selection.include_disabled and not site.enabled:
        return False
    if selection.site_ids and site.site_id.lower() not in {
        item.lower() for item in selection.site_ids
    }:
        return False
    if not _matches_text_filter(site.cluster_id, selection.cluster_ids):
        return False
    if not _matches_text_filter(site.region_id, selection.regions):
        return False
    if not _matches_text_filter(site.cluster_family, selection.families):
        return False
    if not _matches_text_filter(site.cluster_scale, selection.scales):
        return False
    if not _matches_text_filter(site.site_status, selection.statuses):
        return False
    if not _matches_text_filter(site.maturity, selection.maturity_levels):
        return False
    if selection.tags:
        site_tags = {item.lower() for item in site.tags}
        required_tags = {item.lower() for item in selection.tags}
        if not required_tags.issubset(site_tags):
            return False
    return True


def filter_sites(
    sites: Sequence[RegionalLabSiteRecord],
    *,
    selection: RegionalLabSelectionConfig,
) -> list[RegionalLabSiteRecord]:
    """Filter and stably sort site records."""
    selected = [site for site in sites if _site_matches_selection(site, selection=selection)]
    selected.sort(
        key=lambda site: (
            "" if site.region_id is None else site.region_id.lower(),
            "" if site.cluster_id is None else site.cluster_id.lower(),
            site.site_id.lower(),
        )
    )
    if selection.limit is not None:
        return selected[: int(selection.limit)]
    return selected


def _rule_matches_site(
    site: RegionalLabSiteRecord,
    *,
    rule: RegionalLabClusterRuleConfig,
) -> bool:
    """Return whether one cluster-enrichment rule applies to one site."""
    if not _site_matches_selection(site, selection=rule.selection):
        return False
    for field_name, expected_value in rule.field_equals:
        actual_value = _normalize_text(site.raw.get(field_name))
        if (actual_value or "").lower() != expected_value.lower():
            return False
    return True


def apply_cluster_rules(
    sites: Sequence[RegionalLabSiteRecord],
    *,
    cluster_rules: Sequence[RegionalLabClusterRuleConfig],
) -> list[RegionalLabSiteRecord]:
    """Apply explicit cluster-enrichment rules on top of raw catalog rows."""
    ordered_rules = sorted(
        (rule for rule in cluster_rules if rule.enabled),
        key=lambda rule: (int(rule.priority), rule.id.lower()),
    )
    if not ordered_rules:
        return list(sites)

    enriched_sites: list[RegionalLabSiteRecord] = []
    for site in sites:
        current = site
        for rule in ordered_rules:
            if not _rule_matches_site(current, rule=rule):
                continue
            can_override_cluster = rule.override_existing_cluster or current.cluster_id is None
            can_override_label = rule.override_existing_cluster or current.cluster_label is None
            can_override_family = rule.override_existing_cluster or current.cluster_family is None
            can_override_scale = rule.override_existing_cluster or current.cluster_scale is None
            current = replace(
                current,
                cluster_id=(
                    rule.set_cluster_id
                    if rule.set_cluster_id is not None and can_override_cluster
                    else current.cluster_id
                ),
                cluster_label=(
                    rule.set_cluster_label
                    if rule.set_cluster_label is not None and can_override_label
                    else current.cluster_label
                ),
                cluster_family=(
                    rule.set_cluster_family
                    if rule.set_cluster_family is not None and can_override_family
                    else current.cluster_family
                ),
                cluster_scale=(
                    rule.set_cluster_scale
                    if rule.set_cluster_scale is not None and can_override_scale
                    else current.cluster_scale
                ),
                cluster_tags=_merge_tags(current.cluster_tags, rule.cluster_tags),
            )
        enriched_sites.append(current)
    return enriched_sites


def _render_recipe_config_path(
    *,
    cfg: RegionalLabConfig,
    site: RegionalLabSiteRecord,
    recipe: RegionalLabRecipeConfig,
) -> Path:
    """Render and resolve one concrete config path for a site x recipe pair."""
    context = site.build_template_context(lab_id=cfg.lab_id, recipe=recipe)
    try:
        rendered = recipe.config_path_template.format_map(context)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise ValueError(
            f"regional_lab.recipe[{recipe.id}] references unknown template key '{missing_key}'"
        ) from exc
    path = Path(rendered).expanduser()
    if not path.is_absolute():
        path = cfg.base_dir / path
    return path.resolve()


def _evaluate_recipe_site(
    *,
    cfg: RegionalLabConfig,
    site: RegionalLabSiteRecord,
    recipe: RegionalLabRecipeConfig,
) -> tuple[RegionalLabPlannedCase | None, RegionalLabSkippedCase | None]:
    """Expand or skip one site x recipe pair depending on contract completeness."""
    case_id = f"{recipe.id}::{site.site_id}"
    context = site.build_template_context(lab_id=cfg.lab_id, recipe=recipe)
    if recipe.allowed_platforms:
        current_platforms = _current_platform_tokens()
        allowed_platforms = {
            normalized
            for item in recipe.allowed_platforms
            if (normalized := _normalize_platform_token(item)) is not None
        }
        if allowed_platforms and current_platforms.isdisjoint(allowed_platforms):
            return None, RegionalLabSkippedCase(
                case_id=case_id,
                site=site,
                recipe_id=recipe.id,
                recipe_label=recipe.label,
                launcher=recipe.launcher,
                reason="unsupported_platform",
                detail=(
                    "Recipe only supports platform(s): "
                    + ", ".join(sorted(allowed_platforms))
                    + f". Current platform: {', '.join(sorted(current_platforms))}"
                ),
                missing_fields=(),
                config_path=None,
            )
    missing_fields = _normalize_required_field_names(
        context,
        field_names=recipe.required_fields,
    )
    if missing_fields:
        return None, RegionalLabSkippedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            reason="missing_required_fields",
            detail="Missing required field(s): " + ", ".join(missing_fields),
            missing_fields=missing_fields,
            config_path=None,
        )

    config_path = _render_recipe_config_path(cfg=cfg, site=site, recipe=recipe)
    if cfg.validate_config_paths and not config_path.exists():
        return None, RegionalLabSkippedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            reason="missing_config_path",
            detail=f"Resolved child config is missing: {config_path}",
            missing_fields=(),
            config_path=config_path,
        )

    return (
        RegionalLabPlannedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            config_path=config_path,
        ),
        None,
    )


def build_regional_lab_plan(
    cfg: RegionalLabConfig,
    sites: list[RegionalLabSiteRecord],
) -> tuple[
    list[RegionalLabSiteRecord],
    list[RegionalLabPlannedCase],
    list[RegionalLabSkippedCase],
]:
    """Expand the selected sites and recipes into concrete launcher runs."""
    enriched_sites = apply_cluster_rules(sites, cluster_rules=cfg.cluster_rules)
    selected_sites = filter_sites(enriched_sites, selection=cfg.selection)
    planned_cases: list[RegionalLabPlannedCase] = []
    skipped_cases: list[RegionalLabSkippedCase] = []

    for recipe in cfg.recipes:
        if not recipe.enabled:
            continue
        recipe_sites = filter_sites(
            selected_sites,
            selection=recipe.selection,
        )
        for site in recipe_sites:
            planned_case, skipped_case = _evaluate_recipe_site(
                cfg=cfg,
                site=site,
                recipe=recipe,
            )
            if skipped_case is not None:
                skipped_cases.append(skipped_case)
                continue
            if planned_case is not None:
                planned_cases.append(planned_case)

    if not selected_sites:
        raise ValueError("regional_lab selection did not match any site")
    if not planned_cases and not skipped_cases:
        raise ValueError("regional_lab did not expand any runnable or explainable case")
    return selected_sites, planned_cases, skipped_cases


def build_run_command(
    case: RegionalLabPlannedCase,
    *,
    python_executable: Path,
) -> list[str]:
    """Build one child launcher command."""
    if case.launcher == "simulation":
        return [
            str(python_executable),
            "-m",
            "launchers",
            "simulation",
            str(case.config_path),
        ]
    if case.launcher == "method-comparison":
        return [
            str(python_executable),
            "-m",
            "launchers",
            "method-comparison",
            "run",
            str(case.config_path),
        ]
    raise ValueError(f"Unsupported regional-lab launcher: {case.launcher}")
