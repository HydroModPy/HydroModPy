# validity_frame/src/validity_frame/semantic_model/config_loader.py
from __future__ import annotations
from pathlib import Path
from typing import Any

from .meta_model import ModelStructure, PropertiesOfInterest, InfluenceFactors, PropertyDetail
from .context_model import ContextModel
from .validation_store import ValidationStore, UncertaintyDescriptors


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        import tomli
        with open(path, "rb") as f:
            return tomli.load(f)


def _to_property_details(items: list[Any]) -> tuple[PropertyDetail, ...]:
    """Convert a TOML list into a tuple of PropertyDetail.

    Accepts two forms in TOML:
      - plain string : "debit"
      - full table   : {id="debit", name="Flow rate", unit="m3/s", ...}
    """
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(PropertyDetail(id=item, name=item, description=""))
        elif isinstance(item, dict):
            result.append(PropertyDetail(
                id=item.get("id", ""),
                name=item.get("name", item.get("id", "")),
                description=item.get("description", ""),
                unit=item.get("unit"),
                min=item.get("min"),
                max=item.get("max"),
            ))
    return tuple(result)


def load_semantic_model(path: Path) -> dict[str, Any]:
    """Load a user TOML file and return the semantic model objects."""
    data = _load_toml(path)

    sm = data.get("model", {}).get("structure", {})
    model_structure = ModelStructure(
        inputs=tuple(sm.get("inputs", [])),
        outputs=tuple(sm.get("outputs", [])),
        parameters=tuple(sm.get("parameters", [])),
        states=tuple(sm.get("states", [])),
    )

    pi = data.get("properties_of_interest", {})
    properties = PropertiesOfInterest(
        known=_to_property_details(pi.get("known", [])),
        unknown=_to_property_details(pi.get("unknown", [])),
    )

    gm = data.get("influence_factors", {})
    influence = InfluenceFactors(
        measurable=_to_property_details(gm.get("measurable", [])),
        non_measurable=_to_property_details(gm.get("non_measurable", [])),
    )

    ctx = data.get("context", {})
    context = ContextModel(
        system_name=ctx.get("system", "unknown"),
        outlet_x=ctx.get("outlet_x"),
        outlet_y=ctx.get("outlet_y"),
        crs=ctx.get("crs"),
        aquifer_thickness_m=ctx.get("aquifer_thickness_m"),
        catchment_area_km2=ctx.get("catchment_area_km2"),
        geo_nature=ctx.get("geo_nature", {}),
        attributes=ctx.get("attributes", {}),
        family=ctx.get("family", []),
        k_eff=ctx.get("k_eff", {}),
    )

    val = data.get("validation", {})
    incer_data = val.get("uncertainty", {})
    validation_store = ValidationStore(
        tau=val.get("threshold"),
        metric_name=val.get("metric", "R2"),
        incer=UncertaintyDescriptors(
            log_mean=incer_data.get("log_mean", {}),
            log_std=incer_data.get("log_std", {}),
        ),
    )

    return {
        "model_structure": model_structure,
        "properties_of_interest": properties,
        "influence_factors": influence,
        "context": context,
        "validation_store": validation_store,
    }
