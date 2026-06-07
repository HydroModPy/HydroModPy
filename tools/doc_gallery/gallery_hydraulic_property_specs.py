"""Hydraulic-property gallery family extracted from the main manifest."""

from __future__ import annotations

from .gallery_schema import (
    GalleryCaseSpec,
    GalleryImageAsset,
    GalleryMetricSpec,
    _format_float,
    _format_int,
    _format_scientific,
)

_HYDRAULIC_PROPERTY_SQUARE_METRIC_SPECS = (
    GalleryMetricSpec("Structured cells", "structured_cell_count", _format_int),
    GalleryMetricSpec("Triangular cells", "triangular_cell_count", _format_int),
    GalleryMetricSpec("Minimum K", "k_min_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Maximum K", "k_max_m_per_day", _format_float("m/day", precision=1)),
)

_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS = (
    GalleryMetricSpec("Polygons", "n_polygons", _format_int),
    GalleryMetricSpec("Unique zones", "n_unique_zones", _format_int),
    GalleryMetricSpec("Mesh cells", "n_mesh_cells", _format_int),
    GalleryMetricSpec("Maximum K", "property_max", _format_scientific("m/s")),
)

_HYDRAULIC_PROPERTY_IRREGULAR_METRIC_SPECS = (
    GalleryMetricSpec("Structured cells", "structured_cell_count", _format_int),
    GalleryMetricSpec("Irregular cells", "irregular_cell_count", _format_int),
    GalleryMetricSpec("Minimum K", "k_min_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Maximum K", "k_max_m_per_day", _format_float("m/day", precision=1)),
)

_HYDRAULIC_PROPERTY_DEPTH_METRIC_SPECS = (
    GalleryMetricSpec("Mesh cells", "mesh_cell_count", _format_int),
    GalleryMetricSpec("Surface K", "k_surface_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Deep K", "k_deep_m_per_day", _format_float("m/day", precision=1)),
    GalleryMetricSpec("Depth", "depth_m", _format_float("m", precision=0)),
)


def build_hydraulic_property_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
        GalleryCaseSpec(
            slug="hydraulic_conductivity_square_parameterizations",
            title="Square Field Parameterizations",
            category="hydraulic_properties",
            deck=(
                "Synthetic conductivity and storage examples comparing structured and triangular supports, "
                "inline units, and vertical profiles."
            ),
            summary=(
                "This case builds one compact two-zone square domain and maps the same conductivity field "
                "onto structured and triangular meshes. It also illustrates how inline units and depth-profile "
                "modes are normalized before the solver stage."
            ),
            what_it_shows=(
                "How the same heterogeneous K field maps onto structured and triangular meshes.",
                "How inline values such as `m/day` and `mm/day` are normalized to HydroModPy's SI internals.",
                "How `none`, `exponential`, and `tabulated` depth profiles modify conductivity with depth.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/core/field_param_config.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "hydromodpy/spatial/field/cases/square/field_param_config.toml",
                "tests/unit/field/test_field_param.py",
                "tests/unit/field/test_field_param_config.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_square_parameterizations.png",
                    caption=(
                        "Structured and triangular conductivity maps alongside depth-profile "
                        "and inline-unit examples."
                    ),
                    alt_text="Hydraulic conductivity parameterizations on square synthetic meshes",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_SQUARE_METRIC_SPECS,
            case_setup=(
                "Unit-square domain split by one diagonal into granite and micaschist zones.",
                "Structured and triangular meshes generated from the same target cell count.",
                "Depth dependence illustrated with `none`, `exponential`, and `tabulated` profiles.",
            ),
            metadata={
                "property_case_kind": "square_parameterizations",
                "parameter_ids": ["K", "Sy", "Ss"],
                "parameterization_modes": ["inline", "heterogeneous", "exponential", "tabulated"],
                "supports": ["structured", "triangular_structured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_irregular_mesh",
            title="Irregular Mesh Conductivity Mapping",
            category="hydraulic_properties",
            deck="Conductivity transfer on a synthetic square domain using a stochastic unstructured mesh.",
            summary=(
                "This case reuses the synthetic square field but maps it onto an irregular "
                "triangular mesh alongside a structured baseline. The comparison highlights how "
                "the same property definition behaves on irregular supports."
            ),
            what_it_shows=(
                "How heterogeneous K values transfer onto an irregular triangular mesh.",
                "How the same field looks on a structured baseline for visual comparison.",
                "How irregular supports preserve zone contrasts while adapting to stochastic cell layout.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "tests/unit/field/test_field_param.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_irregular_mesh.png",
                    caption="Structured versus irregular triangular conductivity maps for the same field.",
                    alt_text="Hydraulic conductivity mapped on structured and irregular triangular meshes",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_IRREGULAR_METRIC_SPECS,
            case_setup=(
                "Unit-square domain split into granite and micaschist zones.",
                "Structured baseline generated with 64 target cells.",
                "Irregular triangular mesh generated with a fixed random seed.",
            ),
            metadata={
                "property_case_kind": "irregular_mesh",
                "parameter_ids": ["K"],
                "parameterization_modes": ["heterogeneous"],
                "supports": ["structured", "triangular_unstructured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_depth_dependence",
            title="Depth-Dependent Conductivity",
            category="hydraulic_properties",
            deck="Depth-profiled conductivity maps and profiles rendered on a synthetic square mesh.",
            summary=(
                "This case focuses on vertical attenuation. It renders the same heterogeneous field "
                "at the surface and at depth, alongside profile curves that explain the depth scaling."
            ),
            what_it_shows=(
                "How depth profiles rescale conductivity for a given mesh support.",
                "How surface and deep maps diverge while preserving zone geometry.",
                "How exponential and tabulated profiles compare on the same depth axis.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/spatial/field/core/field_param.py",
                "hydromodpy/spatial/field/cases/square/field_mesh_square.py",
                "hydromodpy/spatial/field/cases/square/field_spatial_square.py",
                "tests/unit/field/test_field_param.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_depth_dependence.png",
                    caption="Surface versus deep conductivity maps with depth-profile curves.",
                    alt_text="Depth-dependent conductivity maps and profiles",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_DEPTH_METRIC_SPECS,
            case_setup=(
                "Unit-square two-zone field mapped onto a structured mesh.",
                "Depth profile applied using exponential and tabulated modes.",
                "Surface (0 m) and deep (40 m) maps rendered for comparison.",
            ),
            metadata={
                "property_case_kind": "depth_dependence",
                "parameter_ids": ["K"],
                "parameterization_modes": ["exponential", "tabulated", "depth_profile"],
                "supports": ["structured"],
                "depth_m": 40.0,
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_geology_transfer_brittany",
            title="Geology-Driven Conductivity Transfer",
            category="hydraulic_properties",
            deck="Conductivity mapping from vector geology polygons onto a local structured mesh using FieldParam.",
            summary=(
                "This case reuses the Brittany geology subset shipped with the repository and the generic "
                "geology-to-field pipeline. A compact figure shows geology zones, the value table keyed by zone, "
                "and the mapped conductivity field."
            ),
            what_it_shows=(
                "How one CSV keyed by geology codes turns into a mesh-ready K field.",
                "How HydroModPy keeps the zone legend and the mapped property view aligned on the same local window.",
                "What a deterministic geology-driven property transfer looks like on versioned demo data.",
            ),
            reproduction_command=(
                "python -m hydromodpy.data.variables.geology.cases.run_geology_property_case "
                "--geology-config-file gallery_geology_config_brittany.toml "
                "--field-param-config-file gallery_field_param_brittany.toml "
                "--no-show-plot"
            ),
            source_paths=(
                "hydromodpy/data/variables/geology/cases/run_geology_property_case.py",
                "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "examples/data/geology/GEO1M_brittany.shp",
                "examples/data/geology/GEO1M_brittany.dbf",
                "examples/data/geology/GEO1M_brittany.shx",
                "examples/data/geology/GEO1M_brittany.prj",
                "examples/data/geology/geology_K_dummy_demo.csv",
                "examples/data/dem/regional_dem_naizin.tif",
                "tests/unit/data_managers/geology/test_geology_property_demo.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_transfer_brittany.png",
                    caption=(
                        "Geology zones, zone-value mapping, and resulting conductivity field on a local mesh."
                    ),
                    alt_text="Geology-driven conductivity transfer on the Brittany subset",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS,
            case_setup=(
                "Local Brittany window extracted from the committed GEO1M subset.",
                "Heterogeneous K values loaded from a versioned CSV keyed by geology codes.",
                "Property transfer computed on a compact structured mesh for documentation stability.",
            ),
            metadata={
                "property_case_kind": "geology_transfer_demo",
                "geology_config_path": "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "field_param_config_path": "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "parameter_ids": ["K"],
                "parameterization_modes": ["csv", "heterogeneous"],
                "supports": ["vector_local", "structured"],
            },
        ),
        GalleryCaseSpec(
            slug="hydraulic_conductivity_geology_transfer_variants",
            title="Geology-Driven Conductivity Variants",
            category="hydraulic_properties",
            deck="Multiple geology-driven conductivity cases compared in tabbed panels.",
            summary=(
                "This case groups several geology-driven conductivity maps, mixing the "
                "structured Brittany demo and triangular mesh bundles from different basins. "
                "Tabs keep the variants compact while emphasizing differences in geography and support."
            ),
            what_it_shows=(
                "How geology-driven conductivity looks on structured and triangular supports.",
                "How different basin contexts change the mapped conductivity patterns.",
                "How a tabbed layout keeps multiple variants readable in the docs.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "hydromodpy/data/variables/geology/cases/run_geology_property_case.py",
                "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "examples/projects/07_mesh_gallery/100km2/mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle/cells.csv",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="property_case",
            image_assets=(
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_brittany.png",
                    caption="Structured Brittany geology transfer (local window).",
                    alt_text="Structured geology transfer in Brittany",
                ),
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_10km2.png",
                    caption="Triangular 10 km2 catchment bundle with geology-driven conductivity.",
                    alt_text="Triangular geology transfer on 10 km2 catchment",
                ),
                GalleryImageAsset(
                    filename="hydraulic_conductivity_geology_variant_100km2.png",
                    caption="Triangular 100 km2 catchment bundle with geology-driven conductivity.",
                    alt_text="Triangular geology transfer on 100 km2 catchment",
                ),
            ),
            metric_specs=_HYDRAULIC_PROPERTY_GEOLOGY_METRIC_SPECS,
            case_setup=(
                "One structured geology transfer (Brittany window).",
                "Two triangular mesh bundles with geology-driven conductivity.",
                "Tabbed display to compare variants without page clutter.",
            ),
            metadata={
                "property_case_kind": "geology_transfer_variants",
                "variant_specs": [
                    {
                        "title": "Structured Brittany",
                        "kind": "brittany",
                        "geology_config_path": "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
                        "field_param_config_path": "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
                    },
                    {
                        "title": "Triangular 10 km2",
                        "kind": "bundle",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/10km2/"
                            "mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                    {
                        "title": "Triangular 100 km2",
                        "kind": "bundle",
                        "bundle_path": (
                            "examples/projects/07_mesh_gallery/100km2/"
                            "mesh_headwater_100km2_outlet_1_geology_rivers_buffer30/bundle"
                        ),
                    },
                ],
                "parameter_ids": ["K"],
                "parameterization_modes": ["csv", "heterogeneous", "bundle"],
                "supports": ["structured", "triangular"],
                "tabbed_variants": True,
            },
        ),
    )


__all__ = ["build_hydraulic_property_specs"]
