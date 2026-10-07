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
import tomllib
import types
import warnings
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock

from docutils import nodes
from sphinx.builders.html import StandaloneHTMLBuilder
from sphinx.util import logging as sphinx_logging
from sphinx.util.docutils import SphinxDirective

_logger = sphinx_logging.getLogger(__name__)

# Silence noisy infrastructure warnings that the build cannot fix:
# - docutils still calls the deprecated optparse frontend on Python 3.13;
# - the Python multiprocessing fork warning fires on every parallel worker
#   when ``-j auto`` is used.
# These do not represent doc-side issues. Filtering them keeps the terminal
# readable so the genuine sphinx warnings remain visible.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="optparse")
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message="This process .* is multi-threaded, use of fork.* may lead to deadlocks",
)
warnings.filterwarnings("ignore", message="The frontend.Option class will be removed")
warnings.filterwarnings(
    "ignore",
    message="The frontend.OptionParser class will be replaced",
)

package_path = Path(__file__).resolve().parents[2]
os.environ["PYTHONPATH"] = ":".join((str(package_path), os.environ.get("PYTHONPATH", "")))


_DOC_REQUIRED_EXTENSIONS = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_polyversion",
    "sphinxcontrib.bibtex",
    "sphinx_favicon",
    "sphinx_sitemap",
    "sphinxext.opengraph",
]
_DOC_REQUIRED_EXTENSIONS.append("sphinx_last_updated_by_git")


def _ensure_required_doc_extensions() -> None:
    def _extension_available(extension: str) -> bool:
        try:
            return find_spec(extension) is not None
        except ModuleNotFoundError:
            return False

    missing_extensions = [
        extension for extension in _DOC_REQUIRED_EXTENSIONS if not _extension_available(extension)
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
sys.path.insert(0, str(Path(__file__).parent / "_ext"))
_ensure_required_doc_extensions()

# sphinx-polyversion exposes per-revision metadata via POLYVERSION_DATA when
# building under `python -m sphinx_polyversion poly.py`. The plain Sphinx CLI
# skips this block and runs as a single-version build.
# _current_version drives the pydata version-switcher highlight. The incremental
# Pages workflow builds one version at a time and passes its name via
# HMP_DOC_VERSION; a local polyversion run overrides it from POLYVERSION_DATA;
# a plain local build falls back to the stable trunk.
_current_version = os.environ.get("HMP_DOC_VERSION") or "main"
if os.environ.get("POLYVERSION_DATA"):
    from sphinx_polyversion import load as _polyversion_load

    _polyversion_load(globals())
    _polyversion_current = globals().get("html_context", {}).get("current")
    if getattr(_polyversion_current, "name", None):
        _current_version = _polyversion_current.name

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


def _install_pyarrow_stub() -> None:
    if "pyarrow" in sys.modules or find_spec("pyarrow") is not None:
        return

    module = types.ModuleType("pyarrow")
    module.__version__ = "0.0.0"
    module.__path__ = []

    parquet_module = types.ModuleType("pyarrow.parquet")
    dataset_module = types.ModuleType("pyarrow.dataset")

    def __getattr__(name: str):
        value = MagicMock(name=f"pyarrow.{name}")
        setattr(module, name, value)
        return value

    def _submodule_getattr(module_name: str):
        def _getattr(name: str):
            value = MagicMock(name=f"{module_name}.{name}")
            return value

        return _getattr

    module.__getattr__ = __getattr__  # type: ignore[attr-defined]
    parquet_module.__getattr__ = _submodule_getattr("pyarrow.parquet")  # type: ignore[attr-defined]
    dataset_module.__getattr__ = _submodule_getattr("pyarrow.dataset")  # type: ignore[attr-defined]
    sys.modules["pyarrow"] = module
    sys.modules["pyarrow.parquet"] = parquet_module
    sys.modules["pyarrow.dataset"] = dataset_module


_install_pyarrow_stub()


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

# Single source of truth: pyproject.toml, read from the tree being built. The
# installed metadata comes second: an editable install keeps the version it was
# installed with, so a local build would name an older release.
_pyproject = package_path / "pyproject.toml"
if _pyproject.exists():
    release = tomllib.loads(_pyproject.read_text(encoding="utf-8"))["project"]["version"]
else:
    from importlib.metadata import version as _pkg_version

    release = _pkg_version("hydromodpy")

version = ".".join(release.split(".")[:2])

# -- General configuration ---------------------------------------------------

StandaloneHTMLBuilder.supported_image_types = [
    "image/svg+xml",
    "image/gif",
    "image/png",
    "image/jpeg",
]

extensions = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx.ext.mathjax",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinxcontrib.bibtex",
    "sphinx_favicon",
    "sphinx_sitemap",
    "sphinxext.opengraph",
    "sphinx_last_updated_by_git",
    # Local extensions under _ext/. hmp_params registers the others.
    "hmp_directives",
    "hmp_params",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "matplotlib": ("https://matplotlib.org/stable/", None),
    "xarray": ("https://docs.xarray.dev/en/stable/", None),
    "flopy": ("https://flopy.readthedocs.io/en/stable/", None),
}

# The Python API pages are generated by _ext/hmp_api.py with autodoc.
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_rtype = False
autodoc_member_order = "groupwise"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
add_module_names = False
maximum_signature_line_length = 70

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "attrs_inline",
    "attrs_block",
    "substitution",
    "html_image",
]
myst_heading_anchors = 3
# {{ release }} in a page is the version of the package the site is built from.
myst_substitutions = {
    "release": release,
    "version_badge": (
        f"[![version](https://img.shields.io/badge/version-{release}-f59e0b?style=flat-square)]"
        f"(https://pypi.org/project/hydromodpy/{release}/)"
    ),
}

# The tutorial and the guides read the files of example 04.
hmp_example_dir = str(
    package_path / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
)

bibtex_bibfiles = ["theory/references.bib"]
bibtex_default_style = "alpha"
bibtex_reference_style = "author_year"

suppress_warnings = ["myst.header"]

favicons = [
    {"rel": "icon", "href": "logoHydroModPy.png", "type": "image/png"},
    {"rel": "shortcut icon", "href": "logoHydroModPy.ico", "type": "image/x-icon"},
]

# The site is served at https://docs.hydromodpy.fr/ with one folder per version.
html_baseurl = f"https://docs.hydromodpy.fr/{_current_version}/"
sitemap_url_scheme = "{link}"
ogp_site_url = html_baseurl
ogp_site_name = "HydroModPy"
ogp_image = html_baseurl + "_static/logoHydroModPy_long.png"
ogp_use_first_image = True

git_last_updated_timezone = "Europe/Paris"

_PLANTUML_COMMAND = _resolve_plantuml_command()
if _PLANTUML_COMMAND is not None:
    extensions.append("sphinxcontrib.plantuml")
    plantuml = _PLANTUML_COMMAND
    plantuml_output_format = "svg"

templates_path = ["_templates"]
source_suffix = [".rst", ".md"]
master_doc = "index"
language = "en"

# capability_gallery/ is no longer built. Its images stay under _static/ as long
# as a theory page cites them.
exclude_patterns = [
    "_data",
    # api/generated/ is left by builds of the old documentation and ignored by
    # git; this site has no api/ folder.
    "api",
    "capability_gallery",
    "contribute/architecture/layer-matrix.partial.rst",
]

pygments_style = "sphinx"
numfig = True
smart_quotes = False

# -- Options for HTML output -------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = f"HydroModPy {release}"
html_favicon = "images/logoHydroModPy.png"
html_logo = "images/logoHydroModPy_long.png"
html_theme_options = {
    "logo": {
        "image_light": "images/logoHydroModPy_long.png",
        "image_dark": "images/logoHydroModPy_long.png",
    },
    "navbar_start": ["navbar-logo"],
    "navbar_center": ["navbar-nav"],
    "navbar_end": ["version-switcher", "theme-switcher", "navbar-icon-links"],
    "navbar_align": "left",
    "header_links_before_dropdown": 7,
    "switcher": {
        "json_url": "https://docs.hydromodpy.fr/switcher.json",
        "version_match": _current_version,
    },
    "check_switcher": False,
    "show_nav_level": 1,
    "navigation_depth": 3,
    "show_toc_level": 2,
    "navigation_with_keys": True,
    "secondary_sidebar_items": ["page-toc"],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
    "use_edit_page_button": False,
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
    ],
}
html_sidebars = {"index": [], "**": ["sidebar-nav-bs"]}
html_static_path = ["_static"]
html_css_files = [
    "uml-diagrams.css",
    "css/hmp-image-compare.css",
    "css/hmp-page-badges.css",
    "css/hmp-zoom-image.css",
]
html_js_files = [
    "uml-diagrams.js",
    "js/hmp-image-compare.js",
    "js/hmp-zoom-image.js",
]
copybutton_prompt_text = r">>> |\$ |In \[\d+\]: | {2,5}\.\.\.:"
copybutton_prompt_is_regexp = True
copybutton_only_copy_prompt_lines = False

htmlhelp_basename = "HydroModPydoc"


def _regenerate_contract_tables(app) -> None:
    """Regenerate the documentation tables owned by a declared contract.

    Escape hatch: ``HMP_SKIP_CONTRACT_TABLES_GEN=1``.
    """
    if os.environ.get("HMP_SKIP_CONTRACT_TABLES_GEN") == "1":
        _logger.info("[doc_contracts] regeneration skipped (HMP_SKIP_CONTRACT_TABLES_GEN=1)")
        return
    from tools.doc_contracts import generate_all

    generate_all()


def _ensure_doctree_dir_for_late_extension_caches(app, exception) -> None:
    """Keep late build-finished cache writers from failing on a missing doctreedir."""
    if exception is not None:
        return
    doctreedir = getattr(app, "doctreedir", None)
    if doctreedir:
        Path(doctreedir).mkdir(parents=True, exist_ok=True)


def setup(app):
    if _PLANTUML_COMMAND is None:
        app.add_directive("uml", _MissingPlantUMLDirective, override=True)
        app.add_directive("plantuml", _MissingPlantUMLDirective, override=True)
    app.connect("builder-inited", _regenerate_contract_tables)
    app.connect("build-finished", _ensure_doctree_dir_for_late_extension_caches, priority=0)
    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
