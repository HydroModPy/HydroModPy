"""Construction des figures de distribution pour les maillages.

Ce module contient uniquement le rendu :
- preparation des polygones et de la triangulation ;
- superposition des aretes de limites, de geologie et de riviere ;
- construction d'une figure a un ou deux panneaux.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

from hydromodpy_annex.distribution.mesh.lecture import (
    CHAMPS_NUMERIQUES_COULEUR,
    ConfigurationTrace,
    ConfigurationVisualisation,
)


def _charger_matplotlib(*, afficher_fenetre: bool):
    """Charge matplotlib et force un backend non interactif si necessaire."""
    import matplotlib

    if not afficher_fenetre:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass

    from matplotlib import pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.patches import Patch

    return matplotlib, plt, LineCollection, PolyCollection, Patch


def _carte_xy_noeuds(bundle: CatchmentMeshBundle) -> dict[int, tuple[float, float]]:
    """Construit un acces rapide id_noeud -> (x, y)."""
    return {
        int(noeud.node_id): (float(noeud.x), float(noeud.y))
        for noeud in bundle.nodes
    }


def _polygones_cellules(bundle: CatchmentMeshBundle) -> list[list[tuple[float, float]]]:
    """Transforme la connectivite des cellules en polygones matplotlib."""
    carte_noeuds = _carte_xy_noeuds(bundle)
    polygones: list[list[tuple[float, float]]] = []
    for cellule in bundle.cells:
        polygones.append([carte_noeuds[int(noeud)] for noeud in cellule.node_indices])
    return polygones


def _entrees_triangulation(
    bundle: CatchmentMeshBundle,
) -> tuple[list[float], list[float], list[tuple[int, int, int]]]:
    """Produit la triangulation elementaire du maillage.

    Les quadrangles eventuels sont decoupes en triangles via un eventail
    construit a partir du premier sommet.
    """

    indice_local = {
        int(noeud.node_id): idx
        for idx, noeud in enumerate(bundle.nodes)
    }
    x_noeuds = [float(noeud.x) for noeud in bundle.nodes]
    y_noeuds = [float(noeud.y) for noeud in bundle.nodes]
    triangles: list[tuple[int, int, int]] = []

    for cellule in bundle.cells:
        indices = [indice_local[int(noeud)] for noeud in cellule.node_indices]
        if len(indices) < 3:
            continue
        ancre = indices[0]
        for idx in range(1, len(indices) - 1):
            triangles.append((int(ancre), int(indices[idx]), int(indices[idx + 1])))

    return x_noeuds, y_noeuds, triangles


def _valeurs_topographie_noeuds(
    bundle: CatchmentMeshBundle,
) -> tuple[list[float], list[bool]]:
    """Retourne les altitudes nodales et un masque de validite."""
    valeurs: list[float] = []
    valides: list[bool] = []

    for noeud in bundle.nodes:
        if noeud.z_top is None:
            valeurs.append(0.0)
            valides.append(False)
            continue
        valeurs.append(float(noeud.z_top))
        valides.append(True)

    return valeurs, valides


def a_topographie_noeuds_continue(bundle: CatchmentMeshBundle) -> bool:
    """Indique si le bundle permet un rendu topo continu sur les noeuds."""
    _, valides = _valeurs_topographie_noeuds(bundle)
    _, _, triangles = _entrees_triangulation(bundle)
    return any(
        bool(valides[i0] and valides[i1] and valides[i2])
        for i0, i1, i2 in triangles
    )


def _valeurs_numeriques_cellules(
    bundle: CatchmentMeshBundle,
    champ: str,
) -> list[float]:
    """Extrait un champ numerique cellule par cellule."""
    valeurs: list[float] = []
    for cellule in bundle.cells:
        valeur_brute = getattr(cellule, champ)
        if valeur_brute is None:
            valeurs.append(float("nan"))
            continue
        valeurs.append(float(valeur_brute))
    return valeurs


def _valeurs_categorielles_cellules(
    bundle: CatchmentMeshBundle,
    champ: str,
) -> list[str]:
    """Extrait un champ categoriel cellule par cellule."""
    valeurs: list[str] = []
    for cellule in bundle.cells:
        valeur_brute = getattr(cellule, champ)
        if valeur_brute is None or str(valeur_brute).strip() == "":
            valeurs.append("non_renseigne")
            continue
        valeurs.append(str(valeur_brute))
    return valeurs


def _segments_aretes(
    bundle: CatchmentMeshBundle,
    *,
    selecteur,
) -> list[list[tuple[float, float]]]:
    """Construit des segments 2D a partir des aretes du bundle."""
    carte_noeuds = _carte_xy_noeuds(bundle)
    segments: list[list[tuple[float, float]]] = []
    for arete in bundle.edges:
        if not selecteur(arete):
            continue
        segments.append(
            [
                carte_noeuds[int(arete.node_a)],
                carte_noeuds[int(arete.node_b)],
            ]
        )
    return segments


def _mettre_en_forme_axes(ax, *, carte_noeuds: Mapping[int, tuple[float, float]]) -> None:
    """Applique la meme emprise et la meme mise en forme a tous les panneaux."""
    x = [coords[0] for coords in carte_noeuds.values()]
    y = [coords[1] for coords in carte_noeuds.values()]
    xmin = min(x)
    xmax = max(x)
    ymin = min(y)
    ymax = max(y)
    marge_x = 0.03 * max(xmax - xmin, 1.0)
    marge_y = 0.03 * max(ymax - ymin, 1.0)

    ax.set_xlim(xmin - marge_x, xmax + marge_x)
    ax.set_ylim(ymin - marge_y, ymax + marge_y)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")


def _texte_infos(bundle: CatchmentMeshBundle) -> str:
    """Construit le cartouche d'informations synthetiques."""
    metadata = dict(bundle.metadata)
    lignes = [
        f"cellules : {bundle.n_cells}",
        f"noeuds : {bundle.n_nodes}",
        f"aretes : {bundle.n_edges}",
    ]
    crs = metadata.get("crs")
    if crs is not None:
        lignes.append(f"crs : {crs}")
    mode = metadata.get("constraints_mode")
    if mode is not None:
        lignes.append(f"mode : {mode}")
    geologie = bool(metadata.get("geology", {}).get("available", False))
    lignes.append(f"geologie : {'oui' if geologie else 'non'}")
    return "\n".join(lignes)


def _tracer_cellules_numeriques(
    ax,
    *,
    polygones: list[list[tuple[float, float]]],
    valeurs: list[float],
    palette: str,
    couleur_aretes: str,
    epaisseur_aretes: float,
    PolyCollection,
    plt,
) -> None:
    """Trace un fond par cellule pour un champ numerique."""
    collection = PolyCollection(
        polygones,
        array=valeurs,
        cmap=palette,
        edgecolors=couleur_aretes,
        linewidths=epaisseur_aretes,
    )
    ax.add_collection(collection)
    plt.colorbar(collection, ax=ax, fraction=0.04, pad=0.02)


def _tracer_cellules_categorielles(
    ax,
    *,
    polygones: list[list[tuple[float, float]]],
    valeurs: list[str],
    palette: str,
    couleur_aretes: str,
    epaisseur_aretes: float,
    matplotlib,
    PolyCollection,
    Patch,
) -> None:
    """Trace un fond par cellule pour un champ categoriel."""
    categories = sorted(set(valeurs))
    palette_retaillee = matplotlib.colormaps.get_cmap(palette).resampled(
        max(1, len(categories))
    )
    couleurs = {
        categorie: palette_retaillee(idx)
        for idx, categorie in enumerate(categories)
    }
    collection = PolyCollection(
        polygones,
        facecolors=[couleurs[valeur] for valeur in valeurs],
        edgecolors=couleur_aretes,
        linewidths=epaisseur_aretes,
    )
    ax.add_collection(collection)
    ax.legend(
        handles=[
            Patch(facecolor=couleurs[categorie], edgecolor="0.35", label=categorie)
            for categorie in categories
        ],
        title="champ_couleur",
        loc="upper left",
        fontsize=9,
        title_fontsize=10,
        framealpha=0.95,
    )


def _tracer_surcouches(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    configuration_trace: ConfigurationTrace,
    LineCollection,
) -> None:
    """Trace les lignes de limites, de geologie et de riviere."""
    legendes: list[tuple[str, str]] = []

    if configuration_trace.afficher_limites:
        segments = _segments_aretes(
            bundle,
            selecteur=lambda arete: str(arete.edge_kind) == "boundary",
        )
        if segments:
            ax.add_collection(LineCollection(segments, colors="black", linewidths=1.0))
            legendes.append(("Limite", "black"))

    if configuration_trace.afficher_interfaces_geologie:
        segments = _segments_aretes(
            bundle,
            selecteur=lambda arete: str(arete.edge_kind) == "geology_interface",
        )
        if segments:
            ax.add_collection(
                LineCollection(segments, colors="#c85a00", linewidths=1.2)
            )
            legendes.append(("Interface geologique", "#c85a00"))

    if configuration_trace.afficher_aretes_riviere:
        segments = _segments_aretes(
            bundle,
            selecteur=lambda arete: bool(arete.is_river),
        )
        if segments:
            ax.add_collection(
                LineCollection(segments, colors="#1f78b4", linewidths=1.1)
            )
            legendes.append(("Riviere", "#1f78b4"))

    if legendes:
        from matplotlib.lines import Line2D

        ax.add_artist(
            ax.legend(
                handles=[
                    Line2D([0], [0], color=couleur, lw=1.1, label=label)
                    for label, couleur in legendes
                ],
                loc="lower left",
                fontsize=9,
                framealpha=0.95,
                title="Surcouches",
                title_fontsize=10,
            )
        )


def _tracer_annotations_cellules(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    configuration_trace: ConfigurationTrace,
) -> None:
    """Ajoute les ids de cellules si l'option est activee."""
    if not configuration_trace.annoter_identifiants_cellules:
        return

    for cellule in bundle.cells:
        ax.text(
            float(cellule.centroid_x),
            float(cellule.centroid_y),
            str(cellule.cell_id),
            ha="center",
            va="center",
            fontsize=7,
            color="0.15",
        )


def _tracer_panneau_maillage(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    configuration_trace: ConfigurationTrace,
    champ_couleur: str,
    palette: str,
    titre: str,
    afficher_cartouche: bool,
    matplotlib,
    plt,
    LineCollection,
    PolyCollection,
    Patch,
) -> None:
    """Construit un panneau base sur un coloriage par cellule."""
    couleur_aretes = (
        str(configuration_trace.couleur_aretes_maillage)
        if configuration_trace.afficher_aretes_maillage
        else "none"
    )
    epaisseur_aretes = (
        float(configuration_trace.epaisseur_aretes_maillage)
        if configuration_trace.afficher_aretes_maillage
        else 0.0
    )
    polygones = _polygones_cellules(bundle)

    # Le rendu depend du type de champ demande : numerique ou categoriel.
    if champ_couleur in CHAMPS_NUMERIQUES_COULEUR:
        _tracer_cellules_numeriques(
            ax,
            polygones=polygones,
            valeurs=_valeurs_numeriques_cellules(bundle, champ_couleur),
            palette=palette,
            couleur_aretes=couleur_aretes,
            epaisseur_aretes=epaisseur_aretes,
            PolyCollection=PolyCollection,
            plt=plt,
        )
    else:
        _tracer_cellules_categorielles(
            ax,
            polygones=polygones,
            valeurs=_valeurs_categorielles_cellules(bundle, champ_couleur),
            palette=palette,
            couleur_aretes=couleur_aretes,
            epaisseur_aretes=epaisseur_aretes,
            matplotlib=matplotlib,
            PolyCollection=PolyCollection,
            Patch=Patch,
        )

    _tracer_surcouches(
        ax,
        bundle=bundle,
        configuration_trace=configuration_trace,
        LineCollection=LineCollection,
    )
    _tracer_annotations_cellules(
        ax,
        bundle=bundle,
        configuration_trace=configuration_trace,
    )

    carte_noeuds = _carte_xy_noeuds(bundle)
    _mettre_en_forme_axes(ax, carte_noeuds=carte_noeuds)
    ax.set_title(titre)

    if afficher_cartouche:
        ax.text(
            0.99,
            0.01,
            _texte_infos(bundle),
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            bbox={
                "boxstyle": "round",
                "facecolor": "white",
                "alpha": 0.9,
                "edgecolor": "0.7",
            },
        )


def _tracer_panneau_topographie_continue(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    configuration_trace: ConfigurationTrace,
    palette: str,
    titre: str,
    plt,
    LineCollection,
) -> bool:
    """Construit un panneau topographique continu a partir des noeuds."""
    from matplotlib import tri as mtri

    x_noeuds, y_noeuds, triangles = _entrees_triangulation(bundle)
    if not triangles:
        return False

    # On masque les triangles pour lesquels au moins un noeud n'a pas d'altitude.
    z_noeuds, noeuds_valides = _valeurs_topographie_noeuds(bundle)
    masque_triangles = [
        not bool(noeuds_valides[i0] and noeuds_valides[i1] and noeuds_valides[i2])
        for i0, i1, i2 in triangles
    ]
    if all(masque_triangles):
        return False

    triangulation = mtri.Triangulation(x_noeuds, y_noeuds, triangles)
    if any(masque_triangles):
        triangulation.set_mask(masque_triangles)

    # Le shading Gouraud donne un rendu plus proche d'un MNT continu.
    surface = ax.tripcolor(
        triangulation,
        z_noeuds,
        cmap=palette,
        shading="gouraud",
    )
    plt.colorbar(surface, ax=ax, fraction=0.04, pad=0.02)

    if configuration_trace.afficher_aretes_maillage:
        ax.triplot(
            triangulation,
            color=str(configuration_trace.couleur_aretes_maillage),
            linewidth=float(configuration_trace.epaisseur_aretes_maillage),
        )

    _tracer_surcouches(
        ax,
        bundle=bundle,
        configuration_trace=configuration_trace,
        LineCollection=LineCollection,
    )
    _tracer_annotations_cellules(
        ax,
        bundle=bundle,
        configuration_trace=configuration_trace,
    )

    carte_noeuds = _carte_xy_noeuds(bundle)
    _mettre_en_forme_axes(ax, carte_noeuds=carte_noeuds)
    ax.set_title(titre)
    return True


def construire_figure_visualisation(
    bundle: CatchmentMeshBundle,
    *,
    configuration: ConfigurationVisualisation,
):
    """Construit la figure finale de visualisation.

    Le panneau de gauche montre le maillage et ses contraintes.
    Le panneau de droite montre une vue topographique type MNT si demandee.
    """

    matplotlib, plt, LineCollection, PolyCollection, Patch = _charger_matplotlib(
        afficher_fenetre=configuration.afficher_fenetre
    )
    nombre_panneaux = 2 if configuration.trace.afficher_panneau_topographie else 1
    figure, axes = plt.subplots(
        1,
        nombre_panneaux,
        figsize=configuration.trace.taille_figure,
        dpi=configuration.trace.dpi,
    )
    axes = [axes] if nombre_panneaux == 1 else list(axes)

    titre_gauche = configuration.trace.titre
    if titre_gauche is None:
        titre_gauche = (
            "Vue structurelle du maillage\n"
            f"champ_couleur = {configuration.trace.champ_couleur}"
        )

    _tracer_panneau_maillage(
        axes[0],
        bundle=bundle,
        configuration_trace=configuration.trace,
        champ_couleur=configuration.trace.champ_couleur,
        palette=configuration.trace.palette_couleur,
        titre=titre_gauche,
        afficher_cartouche=True,
        matplotlib=matplotlib,
        plt=plt,
        LineCollection=LineCollection,
        PolyCollection=PolyCollection,
        Patch=Patch,
    )

    if configuration.trace.afficher_panneau_topographie:
        titre_droite = configuration.trace.titre_topographie
        if titre_droite is None:
            titre_droite = (
                "Vue topographique continue\n"
                f"champ_topographie = {configuration.trace.champ_topographie}"
            )

        rendu_continu = _tracer_panneau_topographie_continue(
            axes[1],
            bundle=bundle,
            configuration_trace=configuration.trace,
            palette=configuration.trace.palette_topographie,
            titre=titre_droite,
            plt=plt,
            LineCollection=LineCollection,
        )

        # Si le bundle ne fournit pas assez d'altitudes nodales, on retombe
        # proprement sur un rendu par cellule pour ne pas bloquer l'outil.
        if not rendu_continu:
            _tracer_panneau_maillage(
                axes[1],
                bundle=bundle,
                configuration_trace=configuration.trace,
                champ_couleur=configuration.trace.champ_topographie,
                palette=configuration.trace.palette_topographie,
                titre=f"{titre_droite}\nrepli par cellule",
                afficher_cartouche=False,
                matplotlib=matplotlib,
                plt=plt,
                LineCollection=LineCollection,
                PolyCollection=PolyCollection,
                Patch=Patch,
            )

    figure.tight_layout()
    return figure


__all__ = [
    "a_topographie_noeuds_continue",
    "construire_figure_visualisation",
]
