# Configuration Architecture

All validated configuration payloads must be typed Pydantic models.

`dict[str, object]` and `dict[str, dict[str, object]]` are forbidden under
`HydroModPyConfig`, except for free-form key/value mappings listed in
`tools.doc_config.coverage.INTENTIONALLY_OPAQUE_PATHS`.

Hierarchical TOML grammars such as `[a.b.<kind>.<id>]` must be represented as
`dict[str, Annotated[Union[...], Field(discriminator=...)]]` or
`dict[str, BaseModel]`. TOML canonicalization belongs in a
`@model_validator(mode="before")` on the owning model.

The config reference and JSON Schema are derived from `model_fields` only. Do
not add dispatcher tables, alias modules, or normalizer side registries to
document hidden payload schemas.
