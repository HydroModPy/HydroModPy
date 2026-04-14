# -*- coding: utf-8 -*-
"""
Prototype Module: Base Process Config Schema
===========================================

Defines `ProcessSpatialConfig`, the minimal shared Pydantic schema used by
process configuration models.

Concrete process schemas should typically inherit from this class and add
process-specific validation.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel


class ProcessSpatialConfig(BaseModel):
    """Base Pydantic schema shared by `ProcessSpatial` child configurations."""

    model_config = ConfigDict(extra="forbid")

    param_list: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of process parameter identifiers used to build the "
            "runtime `parameters` container."
        ),
    )
    param: Annotated[dict[str, object], ParamLevel("dev")] = Field(
        default_factory=dict,
        description=(
            "Mapping of process parameter identifiers to process-specific payloads."
        ),
    )
    ic: Annotated[object | None, ParamLevel("dev")] = Field(
        default=None,
        description="Process-specific initial-condition payload.",
    )
    bc: Annotated[dict[str, object], ParamLevel("dev")] = Field(
        default_factory=dict,
        description="Mapping of process boundary-condition payloads.",
    )
    sinks_sources: Annotated[dict[str, object], ParamLevel("dev")] = Field(
        default_factory=dict,
        description="Mapping of process sink/source payloads.",
    )
    active_sinks_sources: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of sink/source identifiers that are explicitly activated "
            "for this process. An empty list means no sink/source is active. "
            "Concrete process configs (e.g. FlowConfig) validate the allowed values."
        ),
    )
    active_bc: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered list of boundary-condition identifiers that are explicitly "
            "activated for this process. An empty list means no boundary-condition "
            "package is assembled. "
            "Concrete process configs (e.g. FlowConfig) validate the allowed values."
        ),
    )
