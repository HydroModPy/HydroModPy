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
# ## Working functions

# %% vscode={"languageId": "shellscript"}
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

# %% vscode={"languageId": "shellscript"}
[item['code_bss'] for item in payload['data']]

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

[print('param: ', item['nom_param'], ' \t\t\t| date: ', item['date_debut_prelevement']) for item in payload['data'] if item['bss_id'] == '01832B0594']

# %% vscode={"languageId": "shellscript"}
data = test_river_quality_endpoint_returns_data()

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
loader = ApiWaterQualityLoader(site_type="river", display=True)
station_info = loader._get_station_info("05047200")
print(station_info)

# %%
# Import the ApiWaterQualityLoader
from loaders_api import ApiWaterQualityLoader

# Define the piezometer IDs
bss_ids = ['05047200']

# Create the loader for piezometer water quality data
loader = ApiWaterQualityLoader(
    site_type="river",
    display=True,  # Enable display to see API responses
)

# Load data for all piezometers
print(f"Loading water quality data for {len(bss_ids)} piezometers...")
loader._get_station_info("05047200")

# %% [markdown]
# # Class

# %%
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

from hydromodpy.data_managers.common.base_loaders import BaseApiLoader
from hydromodpy.data_managers.water_quality.water_quality import WaterQuality

API_PZ_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"
API_RIVER_URL = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/analyse_pc"

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}

class ApiWaterQualityLoader(BaseApiLoader):
    """Load water‑quality records from Hub'Eau web services."""

    STATUS_MESSAGES = STATUS_MESSAGES

    def __init__(
        self,
        *,
        site_type: str = "river",
        parameters: Optional[Sequence[str]] = None,
        display: bool = False,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        self.site_type = str(site_type).strip().lower()
        self.parameters = list(parameters) if parameters is not None else None
        self.display = bool(display)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, site_ids: Sequence[str]) -> ApiLoadResult:
        """Load and normalize data for multiple sites.  This is largely a copy of
        :meth:`ApiPiezometerLoader.load` with variable names changed; you will
        need to fill in the API-specific loops below."""
        print(f"Loading data for {len(site_ids)} water-quality sites...")

        all_stations_info = []
        all_metadata = []
        all_data = []
        all_missing_summary = []
        all_samples: Dict[str, WaterQuality] = {}

        for idx, site_id in enumerate(site_ids):
            site_id = str(site_id)
            print(f"\n[{idx + 1}/{len(site_ids)}] Processing site {site_id}")

            station_info = self._get_station_info(site_id)
            if station_info is None:
                print(f"WARNING: site {site_id} not found")
                continue

            station_info["site_id"] = site_id
            all_stations_info.append(station_info)

            metadata = self._build_metadata(site_id, station_info)
            all_metadata.append(metadata)

            data, missing_info = self._get_time_series(site_id, metadata)
            if not data.empty:
                data["site_id"] = site_id
                sample = WaterQuality(
                    site_id=site_id,
                    data=data,
                    metadata=metadata,
                )
                all_samples[site_id] = sample
                all_data.append(sample.data)

            if missing_info:
                missing_info["site_id"] = site_id
                all_missing_summary.append(missing_info)

        return ApiLoadResult(
            stations_info=pd.DataFrame(all_stations_info) if all_stations_info else pd.DataFrame(),
            metadata=pd.DataFrame(all_metadata) if all_metadata else pd.DataFrame(),
            data=pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame(),
            missing_data_summary=pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame(),
            samples=all_samples,
        )

    def _get_station_info(self, site_id: str) -> Optional[dict]:
        # Try to locate a station/representation for the requested id using
        # the appropriate stations endpoint depending on `site_type`.
        site_id = str(site_id)
        if self.site_type.startswith("river"):
            url = API_RIVER_URL
            params = {"size": 20, "format": "json", "code_station": site_id}
        else:
            url = API_PZ_URL
            params = {"size": 20, "format": "json"}
            # prefer the short code when available
            if "/" in site_id:
                params["code_bss"] = site_id
            else:
                params["bss_id"] = site_id

        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as exc:
            print(f"Warning: station lookup failed for {site_id}: {exc}")
            return None
        if not self._check_status_code(response.status_code):
            return None

        payload = response.json()
        if self.display:
            print(payload)
        rows = payload.get("data", [])
        # try to find a directly matching row
        for row in rows:
            for key in ("code_station", "code_bss", "bss_id", "id", "uri_station"):
                if key in row and str(row.get(key)) == site_id:
                    return row
        # fallback to first row when nothing matches
        return rows[0] if rows else None

    def _build_metadata(self, site_id: str, station_info: Mapping[str, object]) -> dict:
        # Extract common fields (best-effort) from station info returned by
        # the Hub'Eau endpoints.  The keys returned by the two endpoints vary
        # so we attempt several candidates.  Prioritize direct coordinate fields
        # (latitude/longitude) over geometry object.
        x_wgs84 = station_info.get("longitude") or station_info.get("longitude_station")
        y_wgs84 = station_info.get("latitude") or station_info.get("latitude_station")

        # Fallback to geometry object if direct fields not found
        if x_wgs84 is None or y_wgs84 is None:
            geometry = station_info.get("geometry")
            if isinstance(geometry, Mapping):
                coords = geometry.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    if x_wgs84 is None:
                        x_wgs84 = coords[0]
                    if y_wgs84 is None:
                        y_wgs84 = coords[1]

        metadata = {
            "site_id": site_id,
            "station_name": station_info.get("libelle_station")
            or station_info.get("nom_station")
            or station_info.get("code_bss")
            or site_id,
            "x_wgs84": x_wgs84,
            "y_wgs84": y_wgs84,
            "x_l93": station_info.get("x_l93"),
            "y_l93": station_info.get("y_l93"),
            "start_date": station_info.get("date_debut_mesure") or station_info.get("date_debut_prelevement") or station_info.get("date_debut"),
            "end_date": station_info.get("date_fin_mesure") or station_info.get("date_fin_prelevement") or station_info.get("date_fin"),
        }

        metadata["start_date"] = self._to_datetime_or_none(metadata["start_date"])
        metadata["end_date"] = self._to_datetime_or_none(metadata["end_date"])
        if metadata["end_date"] is None:
            metadata["end_date"] = datetime.now() - timedelta(days=1)

        return metadata

    def _get_time_series(
        self,
        site_id: str,
        metadata: Optional[dict] = None,
    ) -> Tuple[pd.DataFrame, dict]:
        if metadata is None:
            metadata = {}

        start_date = self.date_start if self.date_start else metadata.get("start_date")
        end_date = self.date_end if self.date_end else metadata.get("end_date")
        if not start_date or not end_date:
            print(f"Start/end date unavailable for {site_id}.")
            return pd.DataFrame(), {}

        print(f"Fetching data for site {site_id} from {start_date} to {end_date}...")
        all_records = []
        current_year = int(start_date.year)
        end_year = int(end_date.year)
        while current_year <= end_year:
            year_start = max(start_date, datetime(current_year, 1, 1))
            year_end = min(end_date, datetime(current_year + 1, 1, 1))
            params = {"size": 20000, "format": "json"}
            # filtering by station id
            if self.site_type.startswith("river"):
                params["code_station"] = site_id
                params["date_debut_prelevement"] = year_start.strftime("%Y-%m-%d")
                params["date_fin_prelevement"] = year_end.strftime("%Y-%m-%d")
                url = API_RIVER_URL
            else:
                # piezometer-style analyses endpoint uses bss_id/code_bss
                if "/" in site_id:
                    params["code_bss"] = site_id
                else:
                    params["bss_id"] = site_id
                params["date_debut_prelevement"] = year_start.strftime("%Y-%m-%d")
                params["date_fin_prelevement"] = year_end.strftime("%Y-%m-%d")
                url = API_PZ_URL

            try:
                response = requests.get(url, params=params, timeout=60)
            except requests.exceptions.RequestException as exc:
                print(f"Warning: analyses chunk fetch failed for {site_id} ({current_year}): {exc}")
                current_year += 1
                continue
            if not self._check_status_code(response.status_code):
                current_year += 1
                continue
            payload = response.json()
            if self.display:
                print(payload)
            all_records.extend(payload.get("data", []))
            current_year += 1

        if not all_records:
            return pd.DataFrame(), {}

        raw_df = pd.DataFrame(all_records)
        clean_df = WaterQuality.process_api_dataframe(
            raw_df,
            site_id=site_id,
            parameters=self.parameters,
        )
        
        # If station metadata didn't have coordinates, try to extract from the first record
        if (metadata.get("x_wgs84") is None or metadata.get("y_wgs84") is None) and not raw_df.empty:
            first_record = raw_df.iloc[0]
            if metadata.get("x_wgs84") is None and "longitude" in first_record.index:
                metadata["x_wgs84"] = first_record["longitude"]
            if metadata.get("y_wgs84") is None and "latitude" in first_record.index:
                metadata["y_wgs84"] = first_record["latitude"]
        
        missing_info = WaterQuality.compute_missing_data(
            clean_df,
            date_column="date_measure",
            start_date=start_date,
            end_date=end_date,
            id_field="site_id",
            id_value=site_id,
            verbose=True,
        )
        return clean_df, missing_info
