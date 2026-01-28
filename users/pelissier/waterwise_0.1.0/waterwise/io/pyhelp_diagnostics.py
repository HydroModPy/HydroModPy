# -*- coding: utf-8 -*-
"""
Created on Mon Jan  5 09:49:09 2026

@author: pelissierm
"""

import os

def diag_path(workdir: str, filename: str = "pyhelp_preprocessing_diagnostic.txt"):
    return os.path.join(workdir, filename)

def diag_reset(workdir: str):
    path = diag_path(workdir)
    with open(path, "w") as f: 
        f.write(f"### Diagnostic ###")
        
def diag_section(workdir: str, name: str):
    path = diag_path(workdir)
    with open(path, "a") as f: 
        f.write("\n")
        f.write("\n")
        f.write(f"### Site {name}")
        
def diag_line(workdir: str, key: str, value):
    path = diag_path(workdir)
    with open(path, "a") as f: 
        f.write("\n")
        f.write(f"{key}: {value}")



























