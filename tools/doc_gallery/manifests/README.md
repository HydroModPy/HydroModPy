# JSON Manifests

These files are meant for small declarative gallery inventories where adding one
case should mostly be data entry, not Python editing.

## Good Fit

- `copy_assets` cases with committed PNG inputs
- stable inventories such as `geographic` or `code_comparison`
- pages whose metadata is mostly title, summary, tabs, and source pointers

## Required Fields Per Case

- `slug`
- `title`
- `category`
- `deck`
- `summary`
- `reproduction_command`
- `generator`
- `image_assets`

`defaults` can provide shared values for `category`, `generator`,
`reproduction_command`, walkthrough links, or common metadata.

## Image Assets

Each `image_assets` entry must declare:

- `filename`
- `caption`
- `alt_text`
- `source_path` for `copy_assets` cases

Filenames must be unique inside one case.

## Guardrails Enforced By The Loader

- slugs must be unique inside one manifest
- categories must exist in `CATEGORY_SPECS`
- `copy_assets` cases must declare at least one image
- `copy_assets` cases must not point to `results_stable/`
- `metadata.lead_image_filenames` and `metadata.tab_specs` can only reference
  declared image filenames

## Minimal Example

```json
{
  "defaults": {
    "category": "geographic",
    "generator": "copy_assets",
    "reproduction_command": "python examples/projects/data_overview/run_data_overview.py"
  },
  "cases": [
    {
      "slug": "example_case",
      "title": "Example Case",
      "deck": "One-line page description.",
      "summary": "Longer paragraph shown on the case page.",
      "what_it_shows": [
        "First reading point.",
        "Second reading point."
      ],
      "source_paths": [
        "examples/capability_gallery/geographic/example_case/example_case.png"
      ],
      "image_assets": [
        {
          "filename": "example_case.png",
          "caption": "Committed figure copied into the docs gallery.",
          "alt_text": "Example gallery case",
          "source_path": "examples/capability_gallery/geographic/example_case/example_case.png"
        }
      ]
    }
  ]
}
```
