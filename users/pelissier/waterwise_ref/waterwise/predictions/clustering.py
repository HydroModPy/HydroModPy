# -*- coding: utf-8 -*-
"""
Created on Tue Mar 17 12:33:11 2026

@author: pelissierm
"""

import pandas as pd
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans

CSV = 'Z:/HDPY_database_forModelling/_climate/_projection/_pyHelpInput/climate_narratives/climate_metrics_with_families.csv'
K = 3

df = pd.read_csv(CSV)

COL_MODEL = "model"
COL_DJF = "dP_DJF"
COL_JJA = "dP_JJA"

X = list(zip(df[COL_DJF], df[COL_JJA]))

kmeans = KMeans(n_clusters=K, random_state=0)
df["cluster"] = kmeans.fit_predict(X)

colors = ["#66c2a5", "#fc8d62", "#8da0cb"]

plt.figure(figsize=(7,7))

for i in range(K):
    subset = df[df["cluster"] == i]
    plt.scatter(subset[COL_DJF], subset[COL_JJA], color=colors[i], label=f"set {i}", s=80)

for _, r in df.iterrows():
    plt.text(r[COL_DJF], r[COL_JJA], r[COL_MODEL], fontsize=11)
    

plt.xlabel("Relative deviation DJF (%)",  fontsize=14)
plt.ylabel("Relative deviation JJA (%)", fontsize=14)
plt.title("Clustering", fontsize=14)
# plt.legend(fontsize=9, markerscale=0.8)
plt.grid(alpha=0.3)

plt.show()