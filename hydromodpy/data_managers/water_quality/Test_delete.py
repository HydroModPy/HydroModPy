# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.1
#   kernelspec:
#     display_name: HydroMod_Refact
#     language: python
#     name: python3
# ---

# %% vscode={"languageId": "shellscript"}
import pandas as pd
import os
import requests
import pytest
from test_wq_api import test_piezometer_quality_endpoint_returns_data

from __future__ import annotations

import requests
import pytest
from pathlib import Path

# %% [markdown]
# # Espace for testing the class

# %% [markdown]
# ## Working functions

# %% vscode={"languageId": "shellscript"}
API_PZ = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/stations"
API_RIVER = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/analyse_pc"

def _probe(url: str) -> dict:
    resp = requests.get(url, params={"size": 500, "format": "json"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    assert isinstance(payload, dict), "response is not a JSON object"
    assert "data" in payload, "missing 'data' key"
    assert isinstance(payload["data"], list), "'data' is not a list"
    return payload

def test_river_quality_endpoint_returns_data():
    """Call the river quality station list and inspect its structure."""
    payload = _probe(API_RIVER)
    if not payload["data"]:
        pytest.skip("river endpoint returned no records")
    first = payload["data"][50]
    print("river sample keys:", list(first.keys()))
    assert isinstance(first, dict)

    # fetch a small chunk of quality data for this river to inspect structure
    river_id = first.get("code_station") or first.get("libelle_station") or first.get("uri_station")
    if not river_id:
        pytest.skip("no identifier found in station record")

    params = {"size": 500, "format": "json"}
    # try to use the short bss_id if available (strip slash part)
    params["code_station"] = river_id

    try:
        resp = requests.get(API_RIVER, params=params, timeout=30)
    except requests.exceptions.RequestException:
        pytest.skip("analyses endpoint request failed")

    if resp.status_code not in (200, 206):
        pytest.skip(f"analyses endpoint returned {resp.status_code}")

    try:
        data_payload = resp.json()
    except Exception:
        pytest.skip("analyses response not JSON")

    if not isinstance(data_payload, dict) or not data_payload.get("data"):
        pytest.skip("analyses endpoint returned no data")

    print(f"payload from analyses for {river_id}:")
    # print(data_payload)
    try:
        import pandas as pd
        df = pd.DataFrame(data_payload.get("data", []))
    except ImportError:
        pass
    
    return df

def test_piezometer_quality_endpoint_returns_data():
    """Call the piezometer quality station list and inspect its structure."""
    payload = _probe(API_PZ)
    if not payload["data"]:
        pytest.skip("piezometer endpoint returned no records")
    first = payload["data"][0]
    print("piezometer sample keys:", list(first.keys()))
    assert isinstance(first, dict)

    # fetch a small chunk of quality data for this piezometer to inspect structure
    pz_id = first.get("code_bss") or first.get("id") or first.get("piezometer_id") or first.get("bss_id")
    if not pz_id:
        pytest.skip("no identifier found in station record")

    # the documentation indicates that the correct data service is
    # /v1/qualite_nappes/analyses.  we supply either bss_id (preferred) or
    # code_bss as query parameter.
    params = {"size": 500, "format": "json"}
    # try to use the short bss_id if available (strip slash part)
    if "/" in pz_id:
        params["code_bss"] = pz_id
    else:
        params["bss_id"] = pz_id

    try:
        resp = requests.get(API_PZ, params=params, timeout=30)
    except requests.exceptions.RequestException:
        pytest.skip("analyses endpoint request failed")

    if resp.status_code not in (200, 206):
        pytest.skip(f"analyses endpoint returned {resp.status_code}")

    try:
        data_payload = resp.json()
    except Exception:
        pytest.skip("analyses response not JSON")

    if not isinstance(data_payload, dict) or not data_payload.get("data"):
        pytest.skip("analyses endpoint returned no data")

    print(f"payload from analyses for {pz_id}:")
    # print(data_payload)
    try:
        import pandas as pd
        df = pd.DataFrame(data_payload.get("data", []))
    except ImportError:
        pass


# %% [markdown]
# # Test code for the river data

# %% vscode={"languageId": "shellscript"}
API_RIVER = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"

payload = _probe(API_RIVER)
if not payload["data"]:
    pytest.skip("river endpoint returned no records")
first = payload["data"][0]

bss_ids = [item['bss_id'] for item in payload['data']]
bss_ids = list(set(bss_ids))

bss_ids

[print('param: ', item['nom_param'], ' \t\t\t| date: ', item['date_debut_prelevement']) for item in payload['data'] if item['bss_id'] == '01832B0592']

# %% vscode={"languageId": "shellscript"}
data = test_river_quality_endpoint_returns_data()

# %% vscode={"languageId": "shellscript"}
data

# %% vscode={"languageId": "shellscript"}
columns = ['code_station', 'libelle_station','date_prelevement', 'heure_prelevement', 
        'resultat', 'libelle_parametre', 'latitude', 'longitude','code_operation', 'code_point_eau_surface', 'code_banque_reference',
       'code_prelevement', 'code_analyse', 'geometry']
data[columns].libelle_parametre.unique()

# %% [markdown]
# # Working code for the piezometer data

# %% vscode={"languageId": "shellscript"}
columns = ['bss_id', 'code_bss', 'nom_departement', 'nom_region', 'precision_coordonnees', 'longitude', 'latitude', 'altitude', 
           'nom_param', 'nom_fraction', 'resultat',
           'nom_methode', 'nom_unite', 'nom_qualification', 'limite_quantification',
       'limite_detection', 'seuil_saturation', 'incertitude_analytique', 'profondeur_investigation']

df = df[columns]
df.nom_param.unique()

# %% [markdown]
# # Load Water Quality Data Using ApiWaterQualityLoader

# %%
# Import the ApiWaterQualityLoader
from loaders_api import ApiWaterQualityLoader
from datetime import datetime

# Define the piezometer IDs
bss_ids = ['01832B0594', '01832B0592', '01832B0593', '01832B0601']

# Create the loader for piezometer water quality data
loader = ApiWaterQualityLoader(
    site_type="pz",
    parameters=None,  # Load all parameters
    display=False,
    date_start=datetime(2000, 1, 1),  # Adjust date range as needed
    date_end=datetime(2024, 12, 31)
)

# Load data for all piezometers
print(f"Loading water quality data for {len(bss_ids)} piezometers...")
result = loader.load(site_ids=bss_ids)

# Display summary
print(f"\n{'='*70}")
print("LOADED DATA SUMMARY")
print('='*70)
print(f"Stations info: {len(result.stations_info)} stations")
print(f"Metadata records: {len(result.metadata)} records")
print(f"Time-series data: {len(result.data)} records")
print(f"Missing data summary: {len(result.missing_data_summary)} records")
print(f"WaterQuality objects: {len(result.samples)} samples")

# Show first few rows of data
if not result.data.empty:
    print(f"\n{'='*70}")
    print("FIRST 5 DATA RECORDS")
    print('='*70)
    print(result.data.head())
    
    print(f"\n{'='*70}")
    print("AVAILABLE COLUMNS")
    print('='*70)
    for col in result.data.columns:
        print(f"  - {col}")

# Store for further analysis
water_quality_result = result
water_quality_samples = result.samples
