"""
Created on Wed Feb 18 17:22:04 2026

@author: ebaioni
"""

# run_analysis.py

import os

os.getcwd()

import numpy as np
import pandas as pd
from hcdm import run_hcdm

# Load your data
filename = r"C:\Users\ebaioni\OneDrive - Université de Rennes\hydromodpy\HCMD\watershed_lithology_all_new.xlsx"
T = pd.read_excel(filename)

# Prepare matrices
K_eff = T["Keq_new"].values

data = pd.read_excel(filename).values

Sch_Brio = data[:, 4]
Sch_Gra_Pri = data[:, 5]
Plu_Paleo = data[:, 6]
Plu_Protero = data[:, 7]
Meta_Paleo = data[:, 8]
Meta_ProPal = data[:, 9]
Meta_Protero = data[:, 10]

Plu = Plu_Paleo + Plu_Protero

Meta = Meta_Paleo + Meta_ProPal + Meta_Protero

A0 = np.column_stack([Sch_Brio, Sch_Gra_Pri, Plu_Paleo, Plu_Protero, Meta])

sumraw = A0.sum(axis=1)
A_lith = A0 / sumraw[:, None]

litho_names = [
    "Schistes Briv",
    "Schistes Prim",
    "Plutonique Paleo",
    "Plutonic Protero",
    "Metamorphic",
]


# Run inversion
Kj, varj, mj, sj = run_hcdm(K_eff, A_lith, litho_names)
