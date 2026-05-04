#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/stable/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import shutil
import sys
import types
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock

from docutils import nodes
from sphinx.builders.html import StandaloneHTMLBuilder
from sphinx.util.docutils import SphinxDirective

package_path = Path(__file__).resolve().parents[3]
os.environ["PYTHONPATH"] = ":".join((str(package_path), os.environ.get("PYTHONPATH", "")))
_DOC_REQUIRED_EXTENSIONS = [
    "nbsphinx",
    "myst_parser",
    "sphinx_gallery",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_togglebutton",
    "sphinx_tabs",
    "sphinx_multiversion",
    "sphinxcontrib.autodoc_pydantic",
]


def _ensure_required_doc_extensions() -> None:
    missing_extensions = [
        extension for extension in _DOC_REQUIRED_EXTENSIONS if find_spec(extension) is None
    ]
    if not missing_extensions:
        return

    missing_display = ", ".join(missing_extensions)
    raise RuntimeError(
        "Local Sphinx docs build is missing required extensions: "
        f"{missing_display}. From the repository root, run "
        '`pip install -e ".[docs]"` or recreate the editable Conda '
        "environment from install/env_hydromodpy_pkg.yml or "
        "install/env_hydromodpy_light_pkg.yml."
    )


def _resolve_vendor_graphviz_dot() -> Path | None:
    relative = ("tools", "vendor", "graphviz", "bin", "dot.exe" if os.name == "nt" else "dot")
    dot_path = package_path.joinpath(*relative)
    return dot_path if dot_path.exists() else None


def _resolve_plantuml_command() -> str | None:
    env_command = os.environ.get("PLANTUML_COMMAND")
    if env_command:
        return env_command

    vendor_jar = package_path / "tools" / "vendor" / "plantuml" / "plantuml.jar"
    if vendor_jar.exists() and shutil.which("java"):
        return f'java -jar "{vendor_jar}"'

    return shutil.which("plantuml")


class _MissingPlantUMLDirective(SphinxDirective):
    optional_arguments = 1
    has_content = True

    def run(self):
        diagram_label = self.arguments[0] if self.arguments else "inline UML block"
        container = nodes.container(classes=["uml-diagram", "uml-diagram-unavailable"])
        message = nodes.paragraph()
        message += nodes.Text("PlantUML rendering skipped for ")
        message += nodes.literal("", diagram_label)
        message += nodes.Text(". Run ")
        message += nodes.literal("", "python tools/setup_plantuml.py")
        message += nodes.Text(" or set ")
        message += nodes.literal("", "PLANTUML_COMMAND")
        message += nodes.Text(" to restore rendered UML diagrams.")
        container += message
        return [container]


_vendor_graphviz_dot = _resolve_vendor_graphviz_dot()
if _vendor_graphviz_dot is not None:
    os.environ.setdefault("GRAPHVIZ_DOT", str(_vendor_graphviz_dot))
    os.environ["PATH"] = str(_vendor_graphviz_dot.parent) + os.pathsep + os.environ.get("PATH", "")

# Make the editable install (or cloned repo) importable without relying on src/
sys.path.insert(0, str(package_path))
sys.path.insert(0, str(package_path / "hydromodpy"))
_ensure_required_doc_extensions()

_DOC_OPTIONAL_IMPORTS = [
    "pint",
    "pydantic_pint",
    "duckdb",
    "flopy",
    "geopandas",
    "geopy",
    "gmsh",
    "h5py",
    "imageio",
    "meshio",
    "netCDF4",
    "plotly",
    "pyproj",
    "rasterio",
    "rioxarray",
    "sklearn",
    "cma",
    "optuna",
    "ultraplot",
    "vedo",
    "whitebox_workflows",
    "xarray",
    "dask",
    "sqlalchemy",
    "zarr",
    "zstandard",
    "pandera",
    "contextily",
    "matplotlib_scalebar",
    "colormap",
]
autodoc_mock_imports = [name for name in _DOC_OPTIONAL_IMPORTS if find_spec(name) is None]


def _install_module_stub(module_name: str) -> None:
    if module_name in sys.modules or find_spec(module_name) is not None:
        return

    module = types.ModuleType(module_name)

    def __getattr__(name: str):
        value = MagicMock(name=f"{module_name}.{name}")
        setattr(module, name, value)
        return value

    module.__getattr__ = __getattr__  # type: ignore[attr-defined]
    sys.modules[module_name] = module


for _module_name in ("pint", "pydantic_pint", "duckdb"):
    _install_module_stub(_module_name)


try:
    import shapely  # noqa: F401
except Exception:
    import types

    shapely_stub = types.ModuleType("shapely")
    geometry_stub = types.ModuleType("shapely.geometry")

    def _dummy_mapping(obj):
        return getattr(obj, "__geo_interface__", obj)

    class _DummyPoint:
        def __init__(self, *args, **kwargs):
            self.__geo_interface__ = {
                "type": "Point",
                "coordinates": args if args else kwargs.get("coordinates", (0, 0)),
            }

    class _DummyPolygon:
        def __init__(self, *args, **kwargs):
            pass

    geometry_stub.mapping = _dummy_mapping
    geometry_stub.Point = _DummyPoint
    geometry_stub.Polygon = _DummyPolygon
    shapely_stub.geometry = geometry_stub

    sys.modules["shapely"] = shapely_stub
    sys.modules["shapely.geometry"] = geometry_stub

# -- Project information -----------------------------------------------------

project = "HydroModPy"
copyright = "2021"
author = "A. Gauvain, R. Abhervé"

# Single source of truth: pyproject.toml (read via importlib.metadata).
# Fallback to hydromodpy.core.version when the package is not installed
# (RTD source checkout before `pip install -e .`).
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        release = _pkg_version("hydromodpy")
    except PackageNotFoundError:
        from hydromodpy.core.version import __version__ as release
except ImportError:
    from hydromodpy.core.version import __version__ as release

# The short X.Y version
version = ".".join(release.split(".")[:2])


# -- General configuration ---------------------------------------------------
StandaloneHTMLBuilder.supported_image_types = [
    "image/svg+xml",
    "image/gif",
    "image/png",
    "image/jpeg",
]
# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.githubpages",
    "sphinx.ext.autosummary",
    "sphinx.ext.mathjax",
    "nbsphinx",
    "sphinx_gallery.load_style",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_togglebutton",
    "sphinx_tabs.tabs",
    "sphinx_multiversion",
    "sphinxcontrib.autodoc_pydantic",
]
autoclass_content = "both"
autosummary_generate = True
nbsphinx_allow_errors = True
nbsphinx_execute = "never"
_PLANTUML_COMMAND = _resolve_plantuml_command()
if _PLANTUML_COMMAND is not None:
    extensions.append("sphinxcontrib.plantuml")
    plantuml = _PLANTUML_COMMAND
    plantuml_output_format = "svg"

# ---------------------------------------------------------------------------
# autodoc-pydantic - configuration des modèles de paramètres
# ---------------------------------------------------------------------------
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_model_hide_paramlist = True
autodoc_pydantic_model_members = True
autodoc_pydantic_model_undoc_members = False  # Hide inherited BaseModel docstrings
autodoc_pydantic_model_member_order = "bysource"
autodoc_pydantic_model_signature_prefix = "class"

autodoc_pydantic_field_show_constraints = False
autodoc_pydantic_field_show_default = True
autodoc_pydantic_field_show_alias = False
autodoc_pydantic_field_list_validators = False
autodoc_pydantic_field_doc_policy = "description"
autodoc_pydantic_field_signature_prefix = ""
autodoc_typehints = "description"
autodoc_pydantic_settings_show_config_summary = False
autodoc_pydantic_settings_show_json = False

nitpick_ignore_regex = [
    ("py:class", r"Annotated\[.*"),
    ("py:class", r"Profile\..*"),
    ("py:class", r"_?duckdb\..*"),
    ("py:class", r"abc\.ABC"),
    ("py:class", r"collections\.abc\..*"),
    ("py:class", r"datetime"),
    ("py:class", r"gpd\..*"),
    ("py:class", r"matplotlib\..*"),
    ("py:class", r"numpy\..*"),
    ("py:class", r"pandas(?:\.|$).*"),
    ("py:class", r"pathlib\..*Path"),
    ("py:class", r"Path"),
    ("py:class", r"pydantic(?:\.main)?\..*"),
    ("py:class", r"torch(?:\.|$).*"),
    ("py:class", r"UUID"),
    ("py:class", r"xarray\..*"),
    ("py:class", r"xr\..*"),
    (
        "py:class",
        r"(AnalysisConfig|Axes|BaseModel|CalibrationConfig|ConfigError|DerivedComputation|"
        r"DerivedResult|DisplayConfig|Domain|DomainConfig|FlowConfig|Grid|HydroModPyConfig|"
        r"LoadedDataContext|MeshCatchmentConfig|Modflow6Config|ModflowConfig|"
        r"ModflowPreprocessOptions|MplFigure|Objective|OverviewSection|PersistenceConfig|"
        r"ResolvedSimulationTimeGrid|ResolvedSteadySimulationTimeGrid|Run|RunResult|"
        r"ScalarObjective|SetupContext|SimulationCatalog|SimulationZarr|SolverConfig|Stack|"
        r"StoragePathResolver|SyntheticGeographicConfig|TransportConfig|WhiteboxWorkflowsBackend|"
        r"WorkspaceConfig)",
    ),
    (
        "py:class",
        r"hydromodpy\.(calibration|config|core|data|project_accessors|results|simulation|solver|"
        r"spatial|workflow)\..*",
    ),
    ("py:func", r"hydromodpy\.config\.schema_export\.export_schema"),
    (
        "py:func",
        r"hydromodpy\.simulation\.extraction\.extractors\.observation_ingest\.ingest_observations",
    ),
    ("py:mod", r"hydromodpy\.results\.field_registry"),
    ("py:mod", r"torch"),
    ("py:obj", r"hydromodpy\.workflow\.internals\.(state\.T|step\.TIn|step\.TOut)"),
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = "en"

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "pydata_sphinx_theme"
html_favicon = "images/logoHydroModPy.png"
html_logo = "images/logoHydroModPy_long.png"

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {
    "logo": {
        "image_light": "images/logoHydroModPy_long.png",
        "image_dark": "images/logoHydroModPy_long.png",
    },
    "announcement": "🚧 Development documentation",
    "navbar_start": ["navbar-logo"],
    "navbar_center": ["navbar-nav"],
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "show_nav_level": 2,
    "navigation_with_keys": True,
    "primary_sidebar_end": ["indices.html"],
    "secondary_sidebar_items": ["page-toc"],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
    "icon_links_label": "HydroModPy Resources",
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/HydroModPy/HydroModPy",
            "icon": "fa-brands fa-github",
            "type": "fontawesome",
        },
        {
            "name": "Issues",
            "url": "https://github.com/HydroModPy/HydroModPy/issues",
            "icon": "fa-solid fa-circle-info",
            "type": "fontawesome",
        },
        {
            "name": "Google Group",
            "url": "https://groups.google.com/g/hydromodpy",
            "icon": "fa-solid fa-envelope",
            "type": "fontawesome",
        },
    ],
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
html_css_files = ["uml-diagrams.css"]
html_js_files = ["uml-diagrams.js"]
copybutton_prompt_text = r">>> |\$ |In \[\d+\]: | {2,5}\.\.\.:"
copybutton_prompt_is_regexp = True
copybutton_only_copy_prompt_lines = False

togglebutton_hint = "Click to show or hide details"
togglebutton_hint_none = True

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}


# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = "HydroModPydoc"


# -- Options for LaTeX output ------------------------------------------------

latex_elements = {
    "extraclassoptions": "openany,oneside"
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',
    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',
    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',
    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, "HydroModPy.tex", "HydroModPy Documentation", author, "report"),
]

latex_logo = "images/logoHydroModPy_long.png"

# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
# man_pages = [
#    (master_doc, 'HydroModPy', 'HydroModPy Documentation',
#     author, 1)
# ]


# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "HydroModPy",
        "HydroModPy Documentation",
        author,
        "HydroModPy",
        "One line description of project.",
        "Miscellaneous",
    ),
]

# -- Extension configuration -------------------------------------------------
autodoc_mock_imports = [
    "certifi",
    "contextily",
    "flopy",
    "geopandas",
    "gdal",
    "geopy",
    "h5py",
    "imageio",
    "ipykernel",
    "ipython",
    "matplotlib_scalebar",
    "netCDF4",
    "osgeo",
    "plotly",
    "pyhelp",
    "pyproj",
    "pyshp",
    "rasterio",
    "rioxarray",
    "spyder",
    "spyder_kernels",
    "pyside6",
    "vedo",
    "vtk",
    "whitebox_workflows",
    "xarray",
]

# use :numref: for references (instead of :ref:)
numfig = True
smart_quotes = False
html_use_smartypants = False


def setup(app):
    if _PLANTUML_COMMAND is None:
        app.add_directive("uml", _MissingPlantUMLDirective, override=True)
        app.add_directive("plantuml", _MissingPlantUMLDirective, override=True)
    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
