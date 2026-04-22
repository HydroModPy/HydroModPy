# -*- coding: utf-8 -*-

import nbformat as nbf
import os, sys
import re
import subprocess
import json
from nbformat.validator import normalize


def _normalize_notebook(notebook):
    _, normalized = normalize(nbf.from_dict(notebook))
    return normalized


def _write_notebook(path, notebook):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(_normalize_notebook(notebook), file, indent=2, ensure_ascii=False)


def py_to_ipynb(py_file_path, ipynb_file_path):
    # Lire le fichier .py
    with open(py_file_path, "r") as py_file:
        lines = py_file.readlines()

    # Créer une nouvelle cellule de code pour chaque ligne
    cells = []
    code = ""
    for line in lines:
        if line.startswith(
            "#%%"
        ):  # Nouvelle cellule (optionnel si vous utilisez des marqueurs de cellule)
            if code:
                cells.append(nbf.v4.new_code_cell(code))
                code = ""
        else:
            code += line

    # Ajouter la dernière cellule si nécessaire
    if code:
        cells.append(nbf.v4.new_code_cell(code))

    # Créer un nouveau notebook
    nb = nbf.v4.new_notebook()
    nb["cells"] = cells

    # Écrire dans le fichier .ipynb
    _write_notebook(ipynb_file_path, nb)


def find_py_files(directory_path):
    py_files = []
    file_name = []

    # Parcourir le répertoire et ses sous-répertoires
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".py"):
                py_files.append(os.path.join(root, file))
                file_name.append(file)
    return py_files, file_name


def find_folders_starting_with_digit(directory_path):
    # Liste des dossiers commençant par un chiffre
    folders_starting_with_digit = []

    # Parcourir les éléments dans le dossier spécifié
    for item in os.listdir(directory_path):
        item_path = os.path.join(directory_path, item)
        # Vérifier si l'élément est un dossier et s'il commence par un chiffre
        if os.path.isdir(item_path) and re.match(r"^\d", item):
            folders_starting_with_digit.append(item)

    return folders_starting_with_digit


def replace_code_in_ipynb(file_path, old_code, new_code):
    # Charger le fichier .ipynb
    with open(file_path, "r", encoding="utf-8") as file:
        notebook_data = json.load(file)

    # Modifier le code dans les cellules de type 'code'
    for cell in notebook_data["cells"]:
        if cell["cell_type"] == "code":
            # Remplacer le code dans les entrées des cellules
            cell["source"] = [line.replace(old_code, new_code) for line in cell["source"]]

    # Sauvegarder les modifications dans le fichier .ipynb
    _write_notebook(file_path, notebook_data)


def clear_empty_cells(notebook_path):
    # Open the notebook file
    with open(notebook_path, "r", encoding="utf-8") as file:
        notebook = json.load(file)

    # Filter out empty code cells
    notebook["cells"] = [
        cell
        for cell in notebook["cells"]
        if cell["cell_type"] != "code" or "".join(cell["source"]).strip() != ""
    ]

    # Save the modified notebook
    _write_notebook(notebook_path, notebook)


def remove_first_cell(notebook_path, output_path):
    # Open the notebook file
    with open(notebook_path, "r", encoding="utf-8") as file:
        notebook = json.load(file)

    # Remove the first cell (index 0)
    notebook["cells"] = notebook["cells"][1:]

    # Save the modified notebook
    _write_notebook(output_path, notebook)


def add_markdown_cell_at_start(notebook_path, markdown_text, output_path):
    # Open the notebook file
    with open(notebook_path, "r", encoding="utf-8") as file:
        notebook = json.load(file)

    # Create a new markdown cell
    markdown_cell = nbf.v4.new_markdown_cell(markdown_text)

    # Insert the markdown cell at the beginning (index 0)
    notebook["cells"].insert(0, markdown_cell)

    # Save the modified notebook
    _write_notebook(output_path, notebook)


# Exemple d'utilisation
HMP_folder = os.path.abspath(
    os.path.join(os.path.abspath(__file__), os.pardir, os.pardir, os.pardir, os.pardir, os.pardir)
)

example_folder = os.path.join(HMP_folder, "examples")
folders = find_folders_starting_with_digit(example_folder)

current = os.path.abspath(os.path.join(os.path.abspath(__file__), os.pardir))
print(current)
for folder in folders:
    path_file, file = find_py_files(os.path.join(example_folder, folder))
    print(file[0].split(".py")[0])

    # Chemin du notebook
    notebook_path = os.path.join(current, file[0].split(".py")[0] + ".ipynb")

    py_to_ipynb(path_file[0], notebook_path)

    old_code = "root_dir = dirname(dirname(dirname(abspath(__file__))))"
    new_code = "root_dir = '" + HMP_folder + "'"
    replace_code_in_ipynb(notebook_path, old_code, new_code)

    clear_empty_cells(notebook_path)
    remove_first_cell(notebook_path, notebook_path)
    add_markdown_cell_at_start(
        notebook_path, "# " + folder.split("_")[-1].capitalize(), notebook_path
    )

    # Commande pour exécuter le notebook
    subprocess.run(
        ["jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", notebook_path]
    )

subprocess.run(
    [sys.executable, os.path.join(current, "update_example_parameters.py")],
    check=True,
)
