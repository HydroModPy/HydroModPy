# -*- coding: utf-8 -*-
"""
Created on Fri May 23 13:45:01 2025

@author: mathi
"""

import os
import pandas as pd
import numpy as np

WORKDIR = "C:/Users/mathi/Dev/pyhelp-master/pyhelp-test/example/example/"
parameters = ["airtemp", "solrad"]


limits = {
    "precip": (0, 500), # mm
    "airtemp": (-50, 60), # °C
    "solrad": (0, 35) # MJ/m²
}

for param in parameters:
    file = os.path.join(WORKDIR, f"{param}_input_data2.csv")
    df = pd.read_csv(file)

    latitude = df.iloc[0].copy()
    longitude = df.iloc[1].copy()
    data = df.iloc[2:].copy()
    data.columns.values[0] = "date"

    data["date"] = pd.to_datetime(data["date"], errors="coerce")

    data = data[(data["date"] >= "1985-01-01") & (data["date"] <= "2022-12-31")]

    data.iloc[:, 1:] = data.iloc[:, 1:].apply(pd.to_numeric, errors="coerce").astype(float)

    if param == "precip":
        #data.iloc[:, 1:] /= 10    
        pass
    
    if param == "solrad":
        data.iloc[:, 1:] *= 0.0864

    lower, upper = limits[param]
    data.iloc[:, 1:] = data.iloc[:, 1:].mask((data.iloc[:, 1:] < lower) | (data.iloc[:, 1:] > upper))

    latitude.iloc[0] = "Latitude (dd)"
    longitude.iloc[0] = "Longitude (dd)"

    output_path = os.path.join(WORKDIR, f"{param}_input_data_cerra_full.csv")
    with open(output_path, "w") as f:
        f.write(",".join(str(x) for x in latitude.values) + "\n")
        f.write(",".join(str(x) for x in longitude.values) + "\n")
        f.write("\n")  # ligne vide
        for _, row in data.iterrows():
            date_str = row["date"].strftime("%d/%m/%Y")
            values_str = ",".join(f"{v:.7f}" if pd.notnull(v) else "" for v in row.iloc[1:])

            f.write(f"{date_str},{values_str}\n")
