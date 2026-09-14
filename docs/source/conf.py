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


def _is_readthedocs_build() -> bool:
    return os.environ.get("READTHEDOCS") == "True"


_DOC_REQUIRED_EXTENSIONS = [
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_polyversion",
    "sphinxcontrib.autodoc_pydantic",
    "sphinx_codeautolink",
    "sphinxcontrib.bibtex",
    "sphinx_autodoc_typehints",
    "sphinxext.rediraffe",
    "sphinx_favicon",
    "sphinx_sitemap",
    "sphinxext.opengraph",
]
if not _is_readthedocs_build():
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
# and Read the Docs builds skip this block and run as a single-version build.
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
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    # Removed because nothing in docs/source used them: nbsphinx (0 .ipynb
    # files), sphinx_gallery.load_style (0 sphx-glr classes),
    # sphinx_togglebutton (0 `.. toggle::`), sphinx_issues (0 :issue:/:pr:/
    # :user:/:commit: roles). sphinx_design covers the collapsible content the
    # togglebutton used to; the capability gallery is generated by
    # tools/doc_gallery and is unrelated to sphinx-gallery.
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinxcontrib.autodoc_pydantic",
    "sphinx_codeautolink",
    "sphinxcontrib.bibtex",
    "sphinx_autodoc_typehints",
    "sphinxext.rediraffe",
    "sphinx_favicon",
    "sphinx_sitemap",
    "sphinxext.opengraph",
    "hmp_directives",
]
if not _is_readthedocs_build():
    extensions.append("sphinx_last_updated_by_git")

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "matplotlib": ("https://matplotlib.org/stable/", None),
    "xarray": ("https://docs.xarray.dev/en/stable/", None),
    "flopy": ("https://flopy.readthedocs.io/en/stable/", None),
}
autoclass_content = "both"
autosummary_generate = True
# Every public subpackage re-exports its surface from submodules and defines
# nothing itself, so without this the package pages render a docstring and
# nothing else. With it, the 17 subpackage pages list their __all__ and each
# public class gets a page carrying its real members. That is 127 pages, all
# with content, against the 1290 empty ones the recursive walk used to emit.
autosummary_imported_members = True
# Sphinx defaults this to True, i.e. __all__ is ignored. Combined with
# autosummary_imported_members that documented whatever a package happened to
# import: typing.Any and importlib.import_module each got a page. Respecting
# __all__ is what makes "public surface" mean something here.
autosummary_ignore_module_all = False

bibtex_bibfiles = ["theory/references.bib"]
bibtex_default_style = "alpha"
bibtex_reference_style = "author_year"

codeautolink_concat_default = True
codeautolink_global_preface = "import hydromodpy"

# Codeautolink cannot match doctests that contain a Traceback block
# (e.g. ``physical_bounds.validate_physical_value`` shows a ValueError
# example). The HTML still renders correctly, only the in-block name
# linking is skipped, so the warning is purely informative.
# ``codeautolink.parse_block`` covers pseudo-code blocks that show contracts
# with ellipses like ``def foo(...) -> ...: ...`` which ast cannot parse.
suppress_warnings = [
    "codeautolink.match_block",
    "codeautolink.parse_block",
    "misc.highlighting_failure",
    # ``typehints_formatter`` has to be a function, so sphinx can never pickle
    # it into the environment cache. The warning is unactionable and is the
    # only thing standing between this build and -W.
    "config.cache",
]

typehints_fully_qualified = False
always_document_param_types = True
typehints_document_rtype = True


def typehints_formatter(annotation, _config):
    if isinstance(annotation, MagicMock):
        return ":py:obj:`typing.Any`"

    module = getattr(annotation, "__module__", None)
    qualname = getattr(annotation, "__qualname__", None)
    if (module is not None and not isinstance(module, str)) or (
        qualname is not None and not isinstance(qualname, str)
    ):
        return ":py:obj:`typing.Any`"

    return None


rediraffe_redirects = "redirects.txt"
rediraffe_branch = "main~1"

# sphinx-favicon: declare logo variants used as favicon. Files live in
# docs/source/_static/ and are copied via html_static_path.
favicons = [
    {"rel": "icon", "href": "logoHydroModPy.png", "type": "image/png"},
    {"rel": "shortcut icon", "href": "logoHydroModPy.ico", "type": "image/x-icon"},
]

# sphinx-sitemap and sphinxext-opengraph: shared base URL for the public docs.
# The site is served at https://docs.hydromodpy.fr/ with one folder per version,
# so the base URL carries the version being built and the canonical links, the
# sitemap entries and the OpenGraph image all resolve to a real page.
html_baseurl = f"https://docs.hydromodpy.fr/{_current_version}/"
sitemap_url_scheme = "{link}"
ogp_site_url = html_baseurl
ogp_site_name = "HydroModPy"
ogp_image = html_baseurl + "_static/logoHydroModPy_long.png"
ogp_use_first_image = True

# sphinx-last-updated-by-git: keep local footer dates without slowing RTD builds.
git_last_updated_timezone = "Europe/Paris"
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

# nitpick_ignore_regex was removed. ``nitpicky`` is never set anywhere in this
# configuration, so the list had no effect, and half of it silenced targets
# under api/generated/ which no longer exists. Turning nitpicky on is a
# separate decision: it would surface every unresolved reference at once, and
# the deploy build now runs with -W.

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix(es) of source filenames.
source_suffix = [".rst", ".md"]

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
exclude_patterns = [
    "user_guide/figures_inventory.partial.rst",
    "architecture/layer-matrix.partial.rst",
]

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
    "navbar_end": ["version-switcher", "theme-switcher", "navbar-icon-links"],
    "switcher": {
        "json_url": "https://docs.hydromodpy.fr/switcher.json",
        "version_match": _current_version,
    },
    "check_switcher": False,
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
html_css_files = [
    "custom.css",
    "uml-diagrams.css",
    "api-reference.css",
    "css/hmp-image-compare.css",
    "css/hmp-feedback.css",
    "css/hmp-page-badges.css",
    "css/hmp-zoom-image.css",
    "css/hmp-config-reference.css",
]
html_js_files = [
    "uml-diagrams.js",
    "js/hmp-image-compare.js",
    "js/hmp-feedback.js",
    "js/hmp-zoom-image.js",
    "js/hmp-config-reference.js",
    "js/hmp-config-search.js",
]
copybutton_prompt_text = r">>> |\$ |In \[\d+\]: | {2,5}\.\.\.:"
copybutton_prompt_is_regexp = True
copybutton_only_copy_prompt_lines = False

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

# -- Extension configuration -------------------------------------------------

# use :numref: for references (instead of :ref:)
numfig = True
smart_quotes = False
html_use_smartypants = False


def _regenerate_config_reference(app) -> None:
    """Regenerate docs/source/user_guide/config_reference/ before each build.

    Failures used to be swallowed. They cannot be: the configuration
    reference is the only part of the documentation a reviewer cannot check
    by reading the source tree, so a broken generator must stop the build
    rather than ship the pages from the previous run. The two calls below
    also used ``app.warn``, which Sphinx removed, so the handler raised
    ``AttributeError`` and hid the real error.

    Set ``HMP_SKIP_CONFIG_REFERENCE_GEN=1`` to build without regenerating.
    """
    if os.environ.get("HMP_SKIP_CONFIG_REFERENCE_GEN") == "1":
        _logger.info("[doc_config] regeneration skipped (HMP_SKIP_CONFIG_REFERENCE_GEN=1)")
        return
    from tools.doc_config import generate_all

    generate_all()


def _regenerate_contract_tables(app) -> None:
    """Regenerate the documentation tables owned by a declared contract.

    Same contract as _regenerate_config_reference. Escape hatch:
    ``HMP_SKIP_CONTRACT_TABLES_GEN=1``.
    """
    if os.environ.get("HMP_SKIP_CONTRACT_TABLES_GEN") == "1":
        _logger.info("[doc_contracts] regeneration skipped (HMP_SKIP_CONTRACT_TABLES_GEN=1)")
        return
    from tools.doc_contracts import generate_all

    generate_all()


def _regenerate_figures_inventory(app) -> None:
    """Regenerate the figures inventory included by user_guide/figures.rst.

    Same contract as _regenerate_config_reference. Escape hatch:
    ``HMP_SKIP_FIGURES_INVENTORY_GEN=1``.
    """
    if os.environ.get("HMP_SKIP_FIGURES_INVENTORY_GEN") == "1":
        _logger.info("[doc_figures] regeneration skipped (HMP_SKIP_FIGURES_INVENTORY_GEN=1)")
        return
    from tools.doc_figures import generate

    generate()


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
    app.connect("builder-inited", _regenerate_config_reference)
    app.connect("builder-inited", _regenerate_contract_tables)
    app.connect("builder-inited", _regenerate_figures_inventory)
    app.connect("build-finished", _ensure_doctree_dir_for_late_extension_caches, priority=0)
    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
