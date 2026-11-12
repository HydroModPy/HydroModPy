"""A key only a pre-release of 2.0 wrote is refused, with every such key.

Each line of ``hydromodpy/config/prerelease_forms.txt`` is one case: the key written in
a document of its own, which a load refuses with its path. The doctor of this version writes nothing on such a file, a sealed run that holds one is
refused the same way, and ``--set`` is refused without a file to rewrite.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config.config_migration import (
    PRERELEASE_FORMS,
    PRERELEASE_FORMS_FILENAME,
    PrereleaseForm,
    fix_config_chain,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_layers,
    migrate_merged_doc,
    migrate_sealed_config_doc,
    prerelease_keys,
)
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.overrides import SET_SOURCE
from hydromodpy.core.version import __version__
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.schema.changes import REGISTER, migrations_of, outlived, removal_of

NO_REWRITE = "This version does not rewrite the file."


def _written(form: PrereleaseForm) -> tuple[dict[str, Any], str]:
    """Return a document that writes *form* alone, and the key a refusal names."""
    parts = form.path.split(".")
    if parts[-1] == "{*}":
        # A table that held tables under free names.
        parts, leaf = parts[:-1], {"x": {"k": 1}}
    else:
        leaf = form.value if form.has_value else 1
    label: list[str] = []
    document: Any = leaf
    for part in reversed(parts):
        if part.endswith("[*]"):
            document = {part[:-3]: [document]}
            label.insert(0, f"{part[:-3]}[0]")
        else:
            name = "x" if part == "{*}" else part
            document = {name: document}
            label.insert(0, name)
    return document, ".".join(label)


@pytest.mark.parametrize("form", PRERELEASE_FORMS, ids=lambda form: form.path)
def test_a_pre_release_form_is_refused_with_its_path_and_the_way_out(
    form: PrereleaseForm, tmp_path: Path
) -> None:
    document, label = _written(form)
    source = tmp_path / "project.toml"
    if form.path == "workspace.project_root":
        # A runtime field today, which the model refuses in a file with its own words.
        assert prerelease_keys(document) == []
        return
    if form.path in {row.old for row in migrations_of("config")}:
        # A row of the register moves this path and its refusal names the new key
        # (tests/refusals/test_forms.py reads that sentence).
        assert prerelease_keys(document) == []
        return

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(document, source=source)

    told = str(refused.value)
    assert told.startswith(f"{source} holds ")
    assert label in told
    assert NO_REWRITE in told
    assert "hmp doctor" not in told


def test_the_list_holds_each_form_once() -> None:
    assert len(PRERELEASE_FORMS) == 175
    assert len({(form.path, repr(form.value)) for form in PRERELEASE_FORMS}) == 175


def test_the_list_leaves_two_minor_versions_after_2_0() -> None:
    assert not outlived("2.0.0", __version__), (
        f"HydroModPy {__version__} still refuses the forms of a pre-release. Delete "
        f"hydromodpy/config/{PRERELEASE_FORMS_FILENAME}, PRERELEASE_FORMS and their readers: "
        "a file of a pre-release is then refused as any unknown key."
    )


def test_the_recipe_of_the_list_names_its_count_and_the_version_it_leaves() -> None:
    recipe = next(row for row in REGISTER.recipes if row.id == "prerelease_forms_refused")

    assert f"one of the {len(PRERELEASE_FORMS)} keys" in recipe.text
    assert f"it leaves in {removal_of('2.0.0')}." in recipe.text


def test_a_value_form_refuses_its_value_and_no_other() -> None:
    form = next(form for form in PRERELEASE_FORMS if form.has_value)
    document, _ = _written(form)
    other, _ = _written(PrereleaseForm(form.path, "something else", has_value=True))

    assert prerelease_keys(document)
    assert prerelease_keys(other) == []


@pytest.mark.parametrize(
    ("document", "key"),
    [
        ({"export": [{"variables": ["head", "mass_accumulated"]}]}, "export[0].variables"),
        ({"display": {"figures": ["head_map", "calibration_posterior"]}}, "display.figures"),
    ],
)
def test_a_value_form_is_found_inside_a_written_list(document: dict, key: str) -> None:
    assert prerelease_keys(document) == [key]
    assert prerelease_keys({"export": [{"variables": ["head"]}]}) == []


def test_the_keys_come_in_the_order_of_the_list_whatever_the_order_of_the_document() -> None:
    document = {
        "flow": {"ic": {"type": "uniform"}},
        "calibration": {"max_iter": 5, "scoring_window": {}},
    }
    assert prerelease_keys(document) == [
        "calibration.scoring_window",
        "calibration.max_iter",
        "flow.ic.type",
    ]
    assert prerelease_keys({"calibration": {"max_iter": 5}, "flow": {}}) == ["calibration.max_iter"]


def test_each_refused_key_carries_its_pointer_and_the_file(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    document = {
        "flow": {"active_bc": ["drainage"]},
        "calibration": {"phases": [{"name": "a", "max_iter": 3}]},
    }

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(document, source=source)

    payload = refused.value.to_dict()
    assert payload["source"] == str(source)
    assert [entry["pointer"] for entry in payload["details"]] == [
        "/calibration/phases/0/max_iter",
        "/flow/active_bc",
    ]
    assert {entry["type"] for entry in payload["details"]} == {"prerelease_form"}
    assert all(NO_REWRITE in entry["msg"] for entry in payload["details"])


def test_a_sealed_refusal_points_at_each_key_and_names_no_file() -> None:
    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc({"simulation": {"run_id": "x"}})

    payload = refused.value.to_dict()
    assert [entry["pointer"] for entry in payload["details"]] == ["/simulation/run_id"]
    assert "source" not in payload


# Texts the alphas wrote, as the tests of the old rules wrote them. Each is refused
# whole, with every key it holds.
ALPHA_TEXTS = {
    "an export of toggles": (
        '[export]\ngeotiff = true\ntimes = "last"\n[export.variables]\nhead = true\n',
        ["export.geotiff", "export.times", "export.variables"],
    ),
    "the old names of [calibration]": (
        "[calibration]\nmax_iter = 5\n[calibration.optimizer_kwargs]\nseed = 1\n",
        ["calibration.optimizer_kwargs", "calibration.max_iter"],
    ),
    "the keys of [simulation]": (
        '[simulation]\non_collision = "version"\nrun_id = "x"\n',
        ["simulation.on_collision", "simulation.run_id"],
    ),
    "the activation lists": (
        '[flow]\nactive_bc = ["drainage"]\nactive_sinks_sources = ["recharge"]\n',
        ["flow.active_bc", "flow.active_sinks_sources"],
    ),
    "a boundary keyed by its kind": (
        "[flow.bc.cauchy.river]\nvalue = 1.0\n",
        ["flow.bc.cauchy"],
    ),
    "a figure timestep": (
        "[display.overrides.head_map]\ntimestep = 3\n",
        ["display.overrides.head_map.timestep"],
    ),
    "the layering of a solver": (
        "[modflow6.sgrid.vertical]\nnlay = 2\n",
        ["modflow6.sgrid.vertical"],
    ),
    "a solver time grid": ("[modflownwt.tgrid]\nnper = 1\n", ["modflownwt.tgrid"]),
    "a directive of an old key": (
        "[calibration]\nmax_iter__delete = true\n",
        ["calibration.max_iter__delete"],
    ),
    "a phase of the alphas": (
        '[[calibration.phases]]\nname = "late"\nmax_iter = 3\n',
        ["calibration.phases[0].max_iter"],
    ),
    "a property under its old id": ("[flow.param.k]\nvalue = 1e-5\n", ["flow.param.k"]),
    "keys transport never read": ("[transport]\nparam_list = []\n", ["transport.param_list"]),
    "a workspace of the alphas": ('[workspace]\nruns_dir = "runs"\n', ["workspace.runs_dir"]),
    "the boolean table of the export toggles": (
        "[export]\ngeotiff = true\n[export.variables]\nhead = true\nbudget = false\n"
        "pathlines = false\nderived = true\n",
        ["export.geotiff", "export.variables"],
    ),
    "a toggle with the concentration variable": (
        "[export]\nnetcdf = true\n[export.variables]\nhead = false\nconcentration = true\n",
        ["export.netcdf", "export.variables"],
    ),
    "the export table under the results": (
        "[simulation.results.export]\nvtu = true\n"
        "[simulation.results.export.variables]\nhead = true\nbudget = false\n",
        ["simulation.results.export"],
    ),
    "a toggle beside times": (
        "[export]\ngeotiff = true\ntimes = 33\n",
        ["export.geotiff", "export.times"],
    ),
    "times beside time": (
        '[export]\ngeotiff = true\ntimes = 33\ntime = "last"\n',
        ["export.geotiff", "export.times"],
    ),
    "toggles beside a display table": (
        '[export]\ngeotiff = true\ncsv_timeseries = true\n\n[display]\ncmap = "magma"\n',
        ["export.geotiff", "export.csv_timeseries"],
    ),
    "the layering of one solver beside the depth model": (
        "[domain.depth_model]\nthickness = 30\n\n"
        '[modflow6.sgrid.vertical]\ngenmtd_lay = "decay"\nnlay = 10\nlay_decay = 1.2\n',
        ["modflow6.sgrid.vertical"],
    ),
    "the layering of nwt beside its other keys": (
        '[modflownwt.sgrid.vertical]\ngenmtd_lay = "constant"\nnlay = 3\n\n'
        '[modflownwt.sgrid.top_sampling]\nmode = "zonal"\n',
        ["modflownwt.sgrid.vertical"],
    ),
    "the layering of both solvers": (
        '[[simulation.process]]\nid = "flow"\nkind = "flow"\nsolvers = ["modflow_nwt"]\n'
        '[modflow6.sgrid.vertical]\ngenmtd_lay = "decay"\nnlay = 10\nlay_decay = 1.2\n'
        '[modflownwt.sgrid.vertical]\ngenmtd_lay = "constant"\nnlay = 3\n',
        ["modflow6.sgrid.vertical", "modflownwt.sgrid.vertical"],
    ),
    "the layering of both solvers beside domain layers": (
        "[domain.layers]\nnlay = 3\n"
        '[modflow6.sgrid.vertical]\ngenmtd_lay = "decay"\nnlay = 10\nlay_decay = 1.2\n'
        '[modflownwt.sgrid.vertical]\ngenmtd_lay = "constant"\nnlay = 3\n',
        ["modflow6.sgrid.vertical", "modflownwt.sgrid.vertical"],
    ),
    "the layering of a solver chosen by the backend": (
        '[solver]\nbackend = "modflow_nwt"\n\n'
        "[modflow6.sgrid.vertical]\nnlay = 10\n[modflownwt.sgrid.vertical]\nnlay = 3\n",
        ["modflow6.sgrid.vertical", "modflownwt.sgrid.vertical"],
    ),
    "a layering written for a solver that does not run": (
        '[solver]\nbackend = "boussinesq"\n\n[modflow6.sgrid.vertical]\nnlay = 5\n',
        ["modflow6.sgrid.vertical"],
    ),
    "a dotted override of the layering": (
        '[[calibration.phases]]\nname = "deep"\n\n[calibration.phases.overrides]\n'
        '"modflownwt.sgrid.vertical.nlay" = 3\n',
        ['calibration.phases[0].overrides."modflownwt.sgrid.vertical.nlay"'],
    ),
    "dotted overrides of the layering of both solvers": (
        '[[calibration.phases]]\nname = "deep"\n\n[calibration.phases.overrides]\n'
        '"modflow6.sgrid.vertical.nlay" = 10\n"modflownwt.sgrid.vertical.nlay" = 3\n',
        [
            'calibration.phases[0].overrides."modflow6.sgrid.vertical.nlay"',
            'calibration.phases[0].overrides."modflownwt.sgrid.vertical.nlay"',
        ],
    ),
    "a dotted layering override beside the current one": (
        '[[calibration.phases]]\nname = "deep"\n\n[calibration.phases.overrides]\n'
        '"domain.layers.nlay" = 2\n"modflow6.sgrid.vertical.nlay" = 3\n',
        ['calibration.phases[0].overrides."modflow6.sgrid.vertical.nlay"'],
    ),
    "the display output folder": (
        '[display]\nenabled = true\noutput_dir = "figures"\n',
        ["display.output_dir"],
    ),
    "the rerun of the best trial with outputs": (
        '[calibration]\nsave_runs = "best_n"\nrerun_best_with_outputs = true\n',
        ["calibration.rerun_best_with_outputs"],
    ),
    "the rerun of the best trial with outputs, off": (
        '[calibration]\nsave_runs = "best_n"\nrerun_best_with_outputs = false\n',
        ["calibration.rerun_best_with_outputs"],
    ),
    "keys a calibration phase writes as overrides": (
        '[[calibration.phases]]\nname = "p"\n[calibration.phases.overrides]\n'
        '"display.output_dir" = "x"\n"calibration.rerun_best_with_outputs" = true\n',
        [
            'calibration.phases[0].overrides."display.output_dir"',
            'calibration.phases[0].overrides."calibration.rerun_best_with_outputs"',
        ],
    ),
    "an old project with a figures folder": (
        '[workspace]\nproject_root = "."\n\n[geographic]\nsource_mode = "synthetic"\n\n'
        '[simulation]\nname = "legacy"\n\n[display]\noutput_dir = "figures"\n',
        ["display.output_dir"],
    ),
    "a section key of the calibration": (
        "[calibration]\nscoring_window = {start = '2001-01-01'}\n",
        ["calibration.scoring_window"],
    ),
    "a directive of the calibration": (
        "[calibration]\noptimizer_kwargs__merge = {sigma = 0.5}\n",
        ["calibration.optimizer_kwargs__merge"],
    ),
    "a key of a calibration phase": (
        "[[calibration.phases]]\nname = 'p'\noptimizer_kwargs = {sigma = 0.5}\n",
        ["calibration.phases[0].optimizer_kwargs"],
    ),
    "a key of the calibration protocol": (
        "[calibration.protocol]\nsteady_engine_options = {sigma = 0.5}\n",
        ["calibration.protocol.steady_engine_options"],
    ),
    "a key of a calibration parameter": (
        "[calibration.parameters.K]\nprior = 'uniform'\n",
        ["calibration.parameters.K.prior"],
    ),
    "a key of an objective block": (
        "[[calibration.objective_blocks]]\nname = 'b'\nmetric = 'nse'\ntransform = 'none'\n",
        ["calibration.objective_blocks[0].transform"],
    ),
    "a dotted override of the calibration window": (
        "[[calibration.phases]]\nname = 'p'\n[calibration.phases.overrides]\n"
        "\"calibration.scoring_window\" = {start = '2001-01-01'}\n",
        ['calibration.phases[0].overrides."calibration.scoring_window"'],
    ),
    "a bind line of the calibration window": (
        '[sites.bind]\n"calibration.scoring_window" = "w"\n',
        ['sites.bind."calibration.scoring_window"'],
    ),
    "an option of a search": (
        "[calibration]\nmethod = 'scipy_nelder_mead'\nmethod_options = {maxfev = 10}\n",
        ["calibration.method_options.maxfev"],
    ),
    "the margin of the uncertainty": (
        "[calibration.uncertainty]\ntolerance = 0.05\nmode = 'relative'\n",
        ["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
    ),
    "the ratio of an output": (
        "[calibration.outputs.q]\nroptim_max = 2\n",
        ["calibration.outputs.q.roptim_max"],
    ),
    "an uncertainty width of the alphas: tolerance = 0.05": (
        "[calibration]\n[calibration.uncertainty]\ntolerance = 0.05\n",
        ["calibration.uncertainty.tolerance"],
    ),
    'an uncertainty width of the alphas: tolerance = 0.1 + mode = "relative"': (
        '[calibration]\n[calibration.uncertainty]\ntolerance = 0.1\nmode = "relative"\n',
        ["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
    ),
    "an uncertainty width of the alphas: tolerance = 0.07": (
        "[calibration]\n[calibration.uncertainty]\ntolerance = 0.07\n",
        ["calibration.uncertainty.tolerance"],
    ),
    "an uncertainty width of the alphas: tolerance = 75.0": (
        '[calibration]\nobjective = "distance_gap"\n[calibration.uncertainty]\ntolerance = 75.0\n',
        ["calibration.uncertainty.tolerance"],
    ),
    'an uncertainty width of the alphas: mode = "absolute" + tolerance = 25': (
        '[calibration]\nobjective = "distance_gap"\n[calibration.uncertainty]\nmode = "absolute"\ntolerance = 25\n',
        ["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
    ),
    'an uncertainty width of the alphas: mode = "relative" + tolerance = 0.2': (
        '[calibration]\nobjective = "distance_gap"\n[calibration.uncertainty]\nmode = "relative"\ntolerance = 0.2\n',
        ["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
    ),
    "an absolute width with no unit to write": (
        '[calibration]\n[calibration.uncertainty]\nmode = "absolute"\ntolerance = 0.3\n',
        ["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
    ),
    "a width beside a protocol": (
        '[calibration]\nprotocol = "matching_hydrographic_network"\n[calibration.uncertainty]\ntolerance = 0.05\n',
        ["calibration.uncertainty.tolerance"],
    ),
    "the width of each phase": (
        '[calibration.uncertainty]\nmode = "absolute"\n[[calibration.objective_blocks]]\nname = "network"\nmetric = "distance_gap"\n[[calibration.objective_blocks]]\nname = "hydrograph"\nmetric = "nse_log"\n[[calibration.phases]]\nname = "k"\nobjective_blocks = ["network"]\nuncertainty = { tolerance = 225.0 }\n[[calibration.phases]]\nname = "sy"\nobjective_blocks = { hydrograph = 99, network = 1 }\nuncertainty = { mode = "relative", tolerance = 0.1 }\n',
        [
            "calibration.uncertainty.mode",
            "calibration.phases[0].uncertainty.tolerance",
            "calibration.phases[1].uncertainty.tolerance",
            "calibration.phases[1].uncertainty.mode",
        ],
    ),
    "tolerance of the section, a phase and the protocol": (
        "[calibration]\ntolerance = 0.01  # one per cent\n[[calibration.phases]]\nname = 'a'\ntolerance = 0.05\n[calibration.protocol]\nname = 'matching_hydrographic_network'\nsteady_tolerance = 0.01\ntransient_tolerance = 0.05\n",
        [
            "calibration.tolerance",
            "calibration.phases[0].tolerance",
            "calibration.protocol.steady_tolerance",
            "calibration.protocol.transient_tolerance",
        ],
    ),
    "the old budgets and options of every method": (
        '[calibration]\nmethod = "scipy_nelder_mead"\nmax_iter = 60\nmethod_options = { maxfev = 25, xatol = 0.01 }\n[[calibration.phases]]\nname = "a"\nmethod = "cma_es"\nmax_iter = "auto"\nmethod_options = { max_evaluations = 40, popsize = 4 }\n[[calibration.phases]]\nname = "b"\nmethod = "gp_mapping"\nmethod_options = { max_iter = 15, n_init = 5 }\n[[calibration.phases]]\nname = "c"\nmethod = "da_mh_gp"\nmax_iter = 30\nmethod_options = { max_iter = 200 }\n[[calibration.phases]]\nname = "d"\nmethod = "scipy_de"\nmethod_options = { maxiter = 5 }\n[calibration.protocol]\nname = "matching_hydrographic_network"\nsteady_max_iter = 20\ntransient_max_iter = 90\ntransient_method = "scipy_nelder_mead"\ntransient_method_options = { maxfev = 50 }\n',
        [
            "calibration.max_iter",
            "calibration.phases[0].max_iter",
            "calibration.phases[2].max_iter",
            "calibration.protocol.steady_max_iter",
            "calibration.protocol.transient_max_iter",
            "calibration.method_options.maxfev",
            "calibration.phases[0].method_options.max_evaluations",
            "calibration.phases[1].method_options.max_iter",
            "calibration.phases[2].method_options.max_iter",
            "calibration.protocol.transient_method_options.maxfev",
        ],
    ),
    "two budgets of one search": (
        '[calibration]\nmethod = "cma_es"\nmax_iter = 20\nmethod_options = { max_evaluations = 90 }\n',
        ["calibration.max_iter", "calibration.method_options.max_evaluations"],
    ),
    "a phase option that counted evaluations": (
        '[calibration]\nmethod = "scipy_nelder_mead"\nmax_trials = 50\n[[calibration.phases]]\nname = "a"\nmethod_options = { maxfev = 80 }\n[[calibration.phases]]\nname = "b"\nmethod_options = { maxfev = 30 }\n',
        [
            "calibration.phases[0].method_options.maxfev",
            "calibration.phases[1].method_options.maxfev",
        ],
    ),
    "a budget option with no method": (
        "[calibration]\nmethod_options = { max_iter = 20 }\n",
        ["calibration.method_options.max_iter"],
    ),
    "transform and prior of parameters and blocks": (
        '[calibration]\n\n[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\ntransform = "log"  # a conductivity\nprior = "log_uniform"\n\n[calibration.parameters.Sy]\nbounds = [0.01, 0.3]\nprior = "normal"\n\n[[calibration.objective_blocks]]\nname = "network"\nmetric = "distance_gap"\nuses_outputs = ["seepage"]\ntransform = "log"\n\n[[calibration.objective_blocks]]\nname = "hydrograph"\nmetric = "nse_log"\nuses_outputs = ["q"]\n',
        [
            "calibration.parameters.K.transform",
            "calibration.parameters.K.prior",
            "calibration.parameters.Sy.prior",
            "calibration.objective_blocks[0].transform",
        ],
    ),
    "a block whose cost transform leaves metres": (
        '[calibration]\n[calibration.uncertainty]\ntolerance = 0.05\n[[calibration.objective_blocks]]\nname = "network"\nmetric = "distance_gap"\nuses_outputs = ["seepage"]\ntransform = "log"\n',
        ["calibration.objective_blocks[0].transform", "calibration.uncertainty.tolerance"],
    ),
    "a word written under both names": (
        '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\ntransform = "log"\nsearch_space = "identity"\n',
        ["calibration.parameters.K.transform"],
    ),
    "a budget table beside a calibration": (
        '[calibration]\nmethod = "grid"\nobjective = "nse"\n[calibration.parameters.K]\nbounds = [1e-8, 1e-2]\nsearch_space = "log"\n[simulation.results.budget]\nspatial_fields = true\n',
        ["simulation.results.budget"],
    ),
    "a validity ratio on a network output": (
        '[calibration]\nmethod = "bisection"\n[calibration.outputs.net]\nsupport = "network"\nmap.complete = "streams.gpkg"\nroptim_max = 2\n',
        ["calibration.outputs.net.roptim_max"],
    ),
    "a count of skipped samples": (
        "[calibration]\nmax_trials = 3\nwarmup_periods = 12\n",
        ["calibration.warmup_periods"],
    ),
    "a station key beside the gauge": (
        '[site]\ngauge = "NANCON"\n[calibration]\nobserved_station_id = "OTHER"\n',
        ["calibration.observed_station_id"],
    ),
    "both spellings of a figure instant in one table": (
        '[display.overrides.seepage_map]\ntime = "2002-10-15"\ntimestep = 0\n',
        ["display.overrides.seepage_map.timestep"],
    ),
    "a calibration phase override of the figure timestep": (
        '[[calibration.phases]]\nname = "steady"\n[calibration.phases.overrides]\n"display.overrides.seepage_map.timestep" = 0\n',
        ['calibration.phases[0].overrides."display.overrides.seepage_map.timestep"'],
    ),
    "a bottom raster path of geographic": (
        '[geographic]\nsource_mode = "synthetic"\nbottom_path = "bottom.tif"\n',
        ["geographic.bottom_path"],
    ),
    "a project crs of data": (
        '[data]\nproject_crs = "EPSG:2154"\n',
        ["data.project_crs"],
    ),
    "a typename of a hydrography source": (
        '[[data.hydrography.sources]]\nsource = "bdtopage"\ntypename = "sa:CoursEau_FXX_Topage2025"\n',
        ["data.hydrography.sources[0].typename"],
    ),
}


# Documents of runs a pre-release sealed, each refused with every key it holds.
SEALED_ALPHA_DOCUMENTS = {
    "a sealed document with the old precision and width keys": (
        {
            "calibration": {
                "tolerance": 0.02,
                "uncertainty": {"tolerance": 0.05},
                "objective_blocks": [
                    {"name": "network", "metric": "distance_gap"},
                    {"name": "hydrograph", "metric": "nse_log"},
                ],
                "phases": [
                    {
                        "name": "k",
                        "tolerance": 0.01,
                        "objective_blocks": ["network"],
                        "uncertainty": {"tolerance": 80.0},
                    },
                    {
                        "name": "sy",
                        "objective_blocks": ["hydrograph"],
                        "uncertainty": {"mode": "absolute", "tolerance": 0.4},
                    },
                ],
                "protocol": {"steady_tolerance": 0.01, "transient_tolerance": 0.05},
            }
        },
        [
            "calibration.tolerance",
            "calibration.phases[0].tolerance",
            "calibration.protocol.steady_tolerance",
            "calibration.protocol.transient_tolerance",
            "calibration.uncertainty.tolerance",
            "calibration.phases[0].uncertainty.tolerance",
            "calibration.phases[1].uncertainty.tolerance",
            "calibration.phases[1].uncertainty.mode",
        ],
    ),
    "a sealed document with the old budget keys and options": (
        {
            "calibration": {
                "method": "gp_mapping",
                "max_iter": 50,
                "method_options": {"max_iter": 10, "n_init": 4},
                "phases": [
                    {"name": "p", "method": "da_mh_gp", "method_options": {"max_iter": 80}},
                    {"name": "q", "method": "scipy_nelder_mead", "method_options": {"maxfev": 9}},
                ],
                "protocol": {"steady_max_iter": 12},
            }
        },
        [
            "calibration.max_iter",
            "calibration.protocol.steady_max_iter",
            "calibration.method_options.max_iter",
            "calibration.phases[0].method_options.max_iter",
            "calibration.phases[1].method_options.maxfev",
        ],
    ),
    "a sealed document with the three old words": (
        {
            "calibration": {
                "parameters": {
                    "K": {"bounds": [1e-07, 0.001], "transform": "log", "prior": "log_uniform"}
                },
                "objective_blocks": [{"name": "q", "metric": "rmse", "transform": "inverse"}],
            }
        },
        [
            "calibration.parameters.K.transform",
            "calibration.parameters.K.prior",
            "calibration.objective_blocks[0].transform",
        ],
    ),
}


@pytest.mark.parametrize(("text", "keys"), ALPHA_TEXTS.values(), ids=ALPHA_TEXTS.keys())
def test_a_text_of_the_alphas_is_refused_with_every_key_it_holds(
    text: str, keys: list[str], tmp_path: Path
) -> None:
    source = tmp_path / "project.toml"

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(tomllib.loads(text), source=source)

    told = str(refused.value)
    for key in keys:
        assert key in told
    assert told.count(NO_REWRITE) == 1


@pytest.mark.parametrize(
    ("document", "key"),
    [
        pytest.param(
            {"calibration": {"phases": [{"name": "p", "overrides": {"flow.active_bc": []}}]}},
            'calibration.phases[0].overrides."flow.active_bc"',
            id="a phase override",
        ),
        pytest.param(
            {"sites": {"bind": {"calibration.max_iter": "col"}}},
            'sites.bind."calibration.max_iter"',
            id="a bind line",
        ),
        pytest.param(
            {"sites": {"recipes": {"r": {"set": {"export.netcdf": True}}}}},
            'sites.recipes.r.set."export.netcdf"',
            id="a recipe",
        ),
    ],
)
def test_a_dotted_key_of_a_pre_release_is_refused_too(document: dict, key: str) -> None:
    with pytest.raises(ConfigValidationError, match="written by a pre-release") as refused:
        migrate_config_doc(document)

    assert key in str(refused.value)


def test_a_current_document_and_a_form_the_register_moves_are_not_refused() -> None:
    document = {
        "simulation": {"process": [{"id": "flow", "type": "flow", "solvers": ["modflow6"]}]},
        "modflow6": {"process_specific": {"vka": 2.0}},
        "flow": {"bc": {"drainage": {"kind": "drain"}}},
    }

    assert prerelease_keys(document) == []


@pytest.mark.parametrize(
    ("document", "keys"), SEALED_ALPHA_DOCUMENTS.values(), ids=SEALED_ALPHA_DOCUMENTS.keys()
)
def test_a_document_a_pre_release_sealed_is_refused_with_every_key_it_holds(
    document: dict, keys: list[str]
) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc(copy.deepcopy(document))

    told = str(refused.value)
    assert told.startswith("a sealed run config holds ")
    for key in keys:
        assert key in told
    assert told.count(NO_REWRITE) == 1


@pytest.mark.parametrize("buffer", [5, 10, 10.0, 12.5])
def test_a_bare_buffer_is_the_rule_of_version_1_and_loads(buffer: float, tmp_path: Path) -> None:
    """A bare ``buff_area`` reads as ``"N% of sqrt(area)"``, in a file and in a sealed run."""
    document = {"geographic": {"catchment": {"buff_area": buffer}}}

    assert prerelease_keys(document) == []
    migrate_config_doc_on_load(copy.deepcopy(document), source=tmp_path / "project.toml")
    migrate_sealed_config_doc(copy.deepcopy(document))


def test_a_data_section_built_in_python_refuses_the_project_crs_as_unknown() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataConfig(project_crs="EPSG:2154")


def test_a_sealed_run_of_a_pre_release_is_refused_the_same_way() -> None:
    sealed = {"flow": {"active_bc": ["drainage"]}}

    with pytest.raises(ConfigValidationError) as refused:
        migrate_sealed_config_doc(sealed)

    assert str(refused.value).startswith("a sealed run config holds flow.active_bc,")
    assert NO_REWRITE in str(refused.value)


def test_a_sealed_snapshot_keeps_naming_its_project() -> None:
    """``[workspace] project_root`` names the project of a snapshot, read before the migration."""
    snapshot = {"workspace": {"project_root": "/somewhere"}, "simulation": {"name": "x"}}

    migrate_sealed_config_doc(snapshot)

    assert snapshot == {"simulation": {"name": "x"}}


def test_set_is_refused_without_a_file_to_rewrite() -> None:
    with pytest.raises(ConfigValidationError) as refused:
        migrate_layers([(SET_SOURCE, {"flow": {"active_bc": ["drainage"]}})])

    told = str(refused.value)
    assert told.startswith("--set holds flow.active_bc,")
    assert "hmp doctor" not in told
    assert "Write today's name instead" in told


def test_each_layer_that_holds_a_form_is_named(tmp_path: Path) -> None:
    layers = [
        (tmp_path / "parent.toml", {"flow": {"active_bc": []}}),
        (tmp_path / "child.toml", {"simulation": {"run_id": "x"}}),
        (tmp_path / "clean.toml", {"simulation": {"name": "x"}}),
    ]

    with pytest.raises(ConfigValidationError) as refused:
        migrate_layers(layers)

    told = str(refused.value)
    assert "parent.toml holds flow.active_bc" in told
    assert "child.toml holds simulation.run_id" in told
    assert "clean.toml" not in told


def test_a_whole_document_is_refused_when_it_comes_with_no_layer() -> None:
    with pytest.raises(ConfigValidationError, match="config holds flow.active_bc"):
        migrate_merged_doc({"flow": {"active_bc": []}})


def test_the_doctor_refuses_a_chain_of_a_pre_release_and_writes_nothing(tmp_path: Path) -> None:
    parent = tmp_path / "parent.toml"
    child = tmp_path / "child.toml"
    parent.write_text('[flow]\nactive_bc = ["drainage"]\n[modflow6.process_specific]\nvka = 2.0\n')
    child.write_text('base_config = "parent.toml"\n[calibration]\nmax_iter = 5\n')
    written = parent.read_text(), child.read_text()

    with pytest.raises(ConfigValidationError) as refused:
        fix_config_chain(child)

    assert (parent.read_text(), child.read_text()) == written
    told = str(refused.value)
    assert f"{parent} holds flow.active_bc" in told
    assert f"{child} holds calibration.max_iter" in told


def test_hmp_doctor_on_a_file_of_a_pre_release_says_the_way_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from hydromodpy.cli.commands.doctor import fix_config
    from hydromodpy.cli.exit_codes import EXIT_CONFIG

    path = tmp_path / "project.toml"
    path.write_text('[flow]\nactive_bc = ["drainage"]\n', encoding="utf-8")
    written = path.read_text()

    with pytest.raises(SystemExit) as stopped:
        fix_config(str(path))

    assert stopped.value.code == EXIT_CONFIG
    assert path.read_text() == written
    captured = capsys.readouterr()
    assert NO_REWRITE in captured.out + captured.err
