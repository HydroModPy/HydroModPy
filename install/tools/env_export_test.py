# -*- coding: utf-8 -*-
"""
Created on Sat 26 Apr 2025

@author: Bastien Boivin
@contact: bastien.boivin@univ-rennes.fr | bastien.boivin@proton.me

Description:
------------
This script generates a clean `environment.yml` file from an active Conda environment.

Unlike the standard `conda env export` command, which exports *all* installed packages 
including indirect dependencies and build information, this script focuses only on:
    - Packages that were manually installed by the user
    - Their exact currently installed versions
    - Excluding automatically installed dependencies

It combines:
    - `conda env export --from-history` to retrieve the list of manually installed packages
    - `conda list` to retrieve the exact versions currently in use

The resulting `environment.yml` is lightweight, readable, portable, 
and suitable for reliably recreating environments on other machines without bloated metadata.

Usage:
------
    python env_export_test.py --name my_env --output environment.yml

Arguments:
----------
    --name    (optional) Name of the environment (default: current active environment)
    --output  (optional) Output file name (default: auto-detected from OS if not specified)
"""
import os
import argparse
import platform
import subprocess

def get_current_env_name():
    """Get the name of the currently active Conda environment."""
    return os.environ.get("CONDA_DEFAULT_ENV", "base")

def detect_system_suffix():
    """Detect the operating system and architecture to create a suffix for the output file."""
    system = platform.system()
    machine = platform.machine()

    if system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    elif system == "Darwin":
        if machine == "arm64":
            return "mac-arm"
        elif machine == "x86_64":
            return "mac-intel"
        else:
            return "mac-unknown"
    else:
        return "unknown-os"

def generate_environment_yml(env_name=None, output_file=None):
    if env_name is None:
        env_name = get_current_env_name()

    if output_file is None:
        suffix = detect_system_suffix()
        output_file = f"environment-{suffix}.yml"

    history_raw = subprocess.check_output(["conda", "env", "export", "--from-history"], text=True)

    manual_packages = set()
    inside_dependencies = False
    for line in history_raw.splitlines():
        if line.strip() == "dependencies:":
            inside_dependencies = True
            continue
        if inside_dependencies:
            if line.strip().startswith("- "):
                package = line.strip()[2:].split("=")[0]
                manual_packages.add(package)
            else:
                break

    all_packages_raw = subprocess.check_output(["conda", "list"], text=True)

    package_versions = {}
    for line in all_packages_raw.splitlines():
        if not line.startswith("#") and line.strip():
            parts = line.split()
            if len(parts) >= 2:
                package_versions[parts[0]] = parts[1]

    lines = []
    lines.append(f"name: {env_name}")
    lines.append("channels:")
    lines.append("  - conda-forge")
    lines.append("dependencies:")

    for package in sorted(manual_packages):
        version = package_versions.get(package)
        if version:
            lines.append(f"  - {package}={version}")
        else:
            lines.append(f"  - {package}")

    with open(output_file, "w") as f:
        f.write("\n".join(lines))

    print(f"'{output_file}' has been generated for environment '{env_name}'.")

def main():
    parser = argparse.ArgumentParser(description="Export a clean environment.yml from Conda.")
    parser.add_argument("--name", type=str, help="Specify the environment name (default: current active one).")
    parser.add_argument("--output", type=str, help="Specify output file name (default: auto-detected based on OS).")

    args = parser.parse_args()
    generate_environment_yml(env_name=args.name, output_file=args.output)

if __name__ == "__main__":
    main()
