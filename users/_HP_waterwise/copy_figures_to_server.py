# -*- coding: utf-8 -*-
"""
Created on Tue Apr 15 08:25:18 2025

@author: roquesc
"""

import os
import shutil

# Define source and target root paths
out_path = 'Y:/HDPY_models/CR/20250410'  # Root where site folders are
target_server_root = r'C:/Users/roquesc/unine.ch/Waterwise - Documents/Pilot sites/_waterwise_data_process/_maps'  # Change to your server location

# Loop through all site folders
for id_name in os.listdir(out_path):
    if id_name != '_sado':
        continue
    site_folder = os.path.join(out_path, id_name)

    # Ensure it's a directory (site folder)
    if not os.path.isdir(site_folder):
        continue

    stable_folder = os.path.join(site_folder, 'results_stable')
    figures_src = os.path.join(stable_folder, '_figures')

    if os.path.exists(figures_src):
        # Define target path: Z:/.../<id_name>/_figures
        figures_dst = os.path.join(target_server_root, id_name, '_figures')
        
        # Make sure target folders exist
        os.makedirs(os.path.dirname(figures_dst), exist_ok=True)

        # Copy the entire _figures folder
        if os.path.exists(figures_dst):
            shutil.rmtree(figures_dst)  # Clear existing target folder if needed

        shutil.copytree(figures_src, figures_dst)
        print(f"Copied: {id_name}/results_stable/_figures → {figures_dst}")
    else:
        print(f"⚠️ No _figures folder found in: {stable_folder}")