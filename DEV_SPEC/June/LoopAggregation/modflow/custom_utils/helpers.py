import flopy
import os
from pathlib import Path
import pandas as pd

PATH = Path(os.path.dirname(os.path.abspath(__file__)))
MAIN_APP_REPO = str(PATH.parent) + "/"


def importDataFromModel(modelname, dataToLoad):
    """
    param dataToLoad : a list with the type of data to load from the model
    example : ['upw', 'dis']
    """
    return flopy.modflow.Modflow.load(
        modelname + ".nam", verbose=False, check=False, load_only=dataToLoad
    )


def writeExecutionTimeInLogfile(path, modelname, duration):
    with open(path + "/" + modelname + "_log.txt", "w") as file:
        file.write("Execution time (s) of " + modelname + "\n")
        file.write(str(duration))


def getPathToSimulationDirectoryFromModelname(modelname):
    return os.path.join(
        "/".join(os.path.realpath(__file__).split("/")[:-2]), "data", modelname
    )


def getFloodDurationVTUFileNameFromModelnameAndLimitValueForFloodZone(
    modelname, upperLimitForFloodZone
):
    return (
        "VTU_WaterTable_"
        + modelname
        + "_FloodDuration_"
        + str(upperLimitForFloodZone)
        + ".vtu"
    )


def get_path_to_simulation_directory(
    site_number, chronicle, approx, rate, permeability, steady, ref
):
    model_name = get_model_name(
        site_number, chronicle, approx, rate, ref, steady, permeability
    )
    site_name = get_site_name_from_site_number(site_number)
    return os.path.join(MAIN_APP_REPO, "outputs/", site_name, model_name)


def generate_model_name(
    chronicle,
    approx,
    rate,
    ref,
    steady=None,
    site=None,
    time_param=0,
    geology_param=0,
    thickness_param=1,
    permeability_param=86.4,
    theta_param=0.1,
    step=None,
):
    model_name = (
        r"model_"
        + "time_"
        + str(time_param)
        + "_geo_"
        + str(geology_param)
        + "_thick_"
        + str(thickness_param)
    )
    if geology_param == 0:
        model_name = (
            model_name + "_K_" + str(permeability_param) + "_Sy_" + str(theta_param)
        )
    if step is None:
        model_name += "_Step" + str(1)
    else:
        model_name += "_Step" + str(step)
    if site is not None:
        model_name += "_site" + str(site)
    if chronicle is not None:
        model_name += "_Chronicle" + str(chronicle)
    else:
        model_name += "_Chronicle" + str(chronicle)
    if (not ref) and approx is not None and (not steady):
        model_name += "_Approx" + str(approx)
        if approx == 0 or approx == 2:
            model_name += "_Period" + str(float(rate))
        elif approx == 1:
            model_name += "_RechThreshold" + str(float(rate))
    if steady:
        model_name += "_SteadyState"
    return model_name


def get_input_file_name(chronicle, approx, rate, ref, steady, site=None, step=None):
    input_name_suffixe = ""
    if step is None:
        input_name_suffixe += "_Step" + str(1)
    else:
        input_name_suffixe += "_Step" + str(step)
    if site is not None:
        input_name_suffixe += "_site" + str(site)
    if chronicle is not None:
        input_name_suffixe += "_Chronicle" + str(chronicle)
    else:
        input_name_suffixe += "_Chronicle" + str(chronicle)
    if (not ref) and approx is not None and (not steady):
        input_name_suffixe += "_Approx" + str(approx)
        if approx == 0 or approx == 2:
            input_name_suffixe += "_Period" + str(float(rate))
        elif approx == 1:
            input_name_suffixe += "_RechThreshold" + str(float(rate))
    if steady:
        input_name_suffixe += "_SteadyState"

    return "input_file" + input_name_suffixe + ".txt"


def get_model_name(
    site_number, chronicle, approx, rate, ref, steady, permeability=86.4
):
    model_name = (
        "model_time_0_geo_0_thick_1_K_"
        + str(permeability)
        + "_Sy_0.1_Step1_site"
        + str(site_number)
        + "_Chronicle"
        + str(chronicle)
    )
    if steady:
        model_name += "_SteadyState"
    elif not ref:
        model_name += "_Approx" + str(approx)
        if approx == 0 or approx == 2:
            model_name += "_Period" + str(float(rate))
        elif approx == 1:
            model_name += "_RechThreshold" + str(float(rate))
    return model_name


def get_site_name_from_site_number(site_number):
    sites = pd.read_csv(
        MAIN_APP_REPO + "data/study_sites.txt", sep=",", header=0, index_col=0
    )  # \\s+
    site_name = sites.index._data[site_number]
    return site_name
