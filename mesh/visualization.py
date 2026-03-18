"""Construction des figures de distribution pour les maillages.

Ce module ne lit aucun fichier sur disque. Il part d'un bundle deja charge
en memoire et se concentre uniquement sur la fabrication des figures.

Responsabilites principales
---------------------------

- convertir le maillage en objets graphiques simples ;
- colorier les cellules selon un champ numerique ou categoriel ;
- superposer les lignes importantes du maillage ;
- produire une figure finale a un ou deux panneaux.

Le module reste volontairement independant du lecteur du bundle. Il consomme
simplement l'interface minimale documentee dans `models.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

from mesh.models import (
    MeshBundleLike,
    NUMERIC_COLOR_FIELDS,
    PlotConfig,
    VisualizationConfig,
)


def _load_matplotlib(*, show_window: bool):
    """Charge matplotlib et force un backend non interactif si necessaire."""
    import matplotlib

    if not show_window:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass

    from matplotlib import pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.patches import Patch

    return matplotlib, plt, LineCollection, PolyCollection, Patch


def _build_node_xy_map(mesh: MeshBundleLike) -> dict[int, tuple[float, float]]:
    """Construit un acces rapide id_noeud -> (x, y)."""
    return {
        int(node.node_id): (float(node.x), float(node.y))
        for node in mesh.nodes
    }


def _build_cell_polygons(mesh: MeshBundleLike) -> list[list[tuple[float, float]]]:
    """Transforme la connectivite des cellules en polygones matplotlib."""
    node_xy_map = _build_node_xy_map(mesh)
    polygons: list[list[tuple[float, float]]] = []
    for cell in mesh.cells:
        polygons.append([node_xy_map[int(node_id)] for node_id in cell.node_indices])
    return polygons


def _build_triangulation_inputs(
    mesh: MeshBundleLike,
) -> tuple[list[float], list[float], list[tuple[int, int, int]]]:
    """Produit la triangulation elementaire du maillage.

    Les quadrangles eventuels sont decoupes en triangles via un eventail
    construit a partir du premier sommet.
    """

    local_index = {
        int(node.node_id): index
        for index, node in enumerate(mesh.nodes)
    }
    x_values = [float(node.x) for node in mesh.nodes]
    y_values = [float(node.y) for node in mesh.nodes]
    triangles: list[tuple[int, int, int]] = []

    for cell in mesh.cells:
        node_indices = [local_index[int(node_id)] for node_id in cell.node_indices]
        if len(node_indices) < 3:
            continue
        anchor = node_indices[0]
        for index in range(1, len(node_indices) - 1):
            triangles.append(
                (
                    int(anchor),
                    int(node_indices[index]),
                    int(node_indices[index + 1]),
                )
            )

    return x_values, y_values, triangles


def _get_node_topography_values(
    mesh: MeshBundleLike,
) -> tuple[list[float], list[bool]]:
    """Retourne les altitudes nodales et un masque de validite."""
    values: list[float] = []
    valid_mask: list[bool] = []

    for node in mesh.nodes:
        if node.z_top is None:
            values.append(0.0)
            valid_mask.append(False)
            continue
        values.append(float(node.z_top))
        valid_mask.append(True)

    return values, valid_mask


def has_continuous_node_topography(mesh: MeshBundleLike) -> bool:
    """Indique si le bundle permet un rendu topo continu sur les noeuds."""
    _, valid_mask = _get_node_topography_values(mesh)
    _, _, triangles = _build_triangulation_inputs(mesh)
    return any(
        bool(valid_mask[i0] and valid_mask[i1] and valid_mask[i2])
        for i0, i1, i2 in triangles
    )


def _get_numeric_cell_values(
    mesh: MeshBundleLike,
    field_name: str,
) -> list[float]:
    """Extrait un champ numerique cellule par cellule."""
    values: list[float] = []
    for cell in mesh.cells:
        raw_value = getattr(cell, field_name, None)
        if raw_value is None:
            values.append(float("nan"))
            continue
        values.append(float(raw_value))
    return values


def _get_categorical_cell_values(
    mesh: MeshBundleLike,
    field_name: str,
) -> list[str]:
    """Extrait un champ categoriel cellule par cellule."""
    values: list[str] = []
    for cell in mesh.cells:
        raw_value = getattr(cell, field_name)
        if raw_value is None or str(raw_value).strip() == "":
            values.append("non_renseigne")
            continue
        values.append(str(raw_value))
    return values


def _build_edge_segments(
    mesh: MeshBundleLike,
    *,
    selector,
) -> list[list[tuple[float, float]]]:
    """Construit des segments 2D a partir des aretes du bundle."""
    node_xy_map = _build_node_xy_map(mesh)
    segments: list[list[tuple[float, float]]] = []
    for edge in mesh.edges:
        if not selector(edge):
            continue
        segments.append(
            [
                node_xy_map[int(edge.node_a)],
                node_xy_map[int(edge.node_b)],
            ]
        )
    return segments


def _format_axes(ax, *, node_xy_map: Mapping[int, tuple[float, float]]) -> None:
    """Applique la meme emprise et la meme mise en forme a tous les panneaux."""
    x_values = [coords[0] for coords in node_xy_map.values()]
    y_values = [coords[1] for coords in node_xy_map.values()]
    xmin = min(x_values)
    xmax = max(x_values)
    ymin = min(y_values)
    ymax = max(y_values)
    x_margin = 0.03 * max(xmax - xmin, 1.0)
    y_margin = 0.03 * max(ymax - ymin, 1.0)

    ax.set_xlim(xmin - x_margin, xmax + x_margin)
    ax.set_ylim(ymin - y_margin, ymax + y_margin)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")


def _build_info_text(mesh: MeshBundleLike) -> str:
    """Construit le cartouche d'informations synthetiques.

    Ce cartouche sert a expliquer rapidement ce que l'on regarde sans avoir a
    ouvrir les fichiers du bundle a la main.
    """

    metadata = dict(mesh.metadata)
    lines = [
        f"cellules : {mesh.n_cells}",
        f"noeuds : {mesh.n_nodes}",
        f"aretes : {mesh.n_edges}",
    ]
    crs = metadata.get("crs")
    if crs is not None:
        lines.append(f"crs : {crs}")
    constraints_mode = metadata.get("constraints_mode")
    if constraints_mode is not None:
        lines.append(f"mode : {constraints_mode}")
    geology_available = bool(metadata.get("geology", {}).get("available", False))
    lines.append(f"geologie : {'oui' if geology_available else 'non'}")
    return "\n".join(lines)


def _plot_numeric_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    values: list[float],
    color_map: str,
    mesh_edge_color: str,
    mesh_edge_linewidth: float,
    PolyCollection,
    plt,
) -> None:
    """Trace un fond par cellule pour un champ numerique.

    Certains bundles plus anciens ne portent pas encore tous les champs
    numeriques proposes par le viewer. Dans ce cas, on evite un plantage
    lorsque toutes les valeurs sont manquantes et on affiche un fond neutre.
    """
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        collection = PolyCollection(
            polygons,
            facecolors="#d9d9d9",
            edgecolors=mesh_edge_color,
            linewidths=mesh_edge_linewidth,
        )
        ax.add_collection(collection)
        ax.text(
            0.02,
            0.98,
            "Aucune valeur disponible\npour ce champ numerique",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            bbox={
                "boxstyle": "round",
                "facecolor": "white",
                "alpha": 0.9,
                "edgecolor": "0.7",
            },
        )
        return

    collection = PolyCollection(
        polygons,
        array=values,
        cmap=color_map,
        edgecolors=mesh_edge_color,
        linewidths=mesh_edge_linewidth,
    )
    ax.add_collection(collection)
    plt.colorbar(collection, ax=ax, fraction=0.04, pad=0.02)


def _plot_categorical_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    values: list[str],
    color_map: str,
    mesh_edge_color: str,
    mesh_edge_linewidth: float,
    matplotlib,
    PolyCollection,
    Patch,
) -> None:
    """Trace un fond par cellule pour un champ categoriel."""
    categories = sorted(set(values))
    resampled_cmap = matplotlib.colormaps.get_cmap(color_map).resampled(
        max(1, len(categories))
    )
    facecolors_by_category = {
        category: resampled_cmap(index)
        for index, category in enumerate(categories)
    }
    collection = PolyCollection(
        polygons,
        facecolors=[facecolors_by_category[value] for value in values],
        edgecolors=mesh_edge_color,
        linewidths=mesh_edge_linewidth,
    )
    ax.add_collection(collection)
    ax.legend(
        handles=[
            Patch(
                facecolor=facecolors_by_category[category],
                edgecolor="0.35",
                label=category,
            )
            for category in categories
        ],
        title="color_field",
        loc="upper left",
        fontsize=9,
        title_fontsize=10,
        framealpha=0.95,
    )


def _plot_overlays(
    ax,
    *,
    mesh: MeshBundleLike,
    plot_config: PlotConfig,
    LineCollection,
) -> None:
    """Trace les lignes de limites, de geologie et de riviere."""
    legend_items: list[tuple[str, str]] = []

    if plot_config.show_boundaries:
        segments = _build_edge_segments(
            mesh,
            selector=lambda edge: str(edge.edge_kind) == "boundary",
        )
        if segments:
            ax.add_collection(LineCollection(segments, colors="black", linewidths=1.0))
            legend_items.append(("Limite", "black"))

    if plot_config.show_geology_interfaces:
        segments = _build_edge_segments(
            mesh,
            selector=lambda edge: str(edge.edge_kind) == "geology_interface",
        )
        if segments:
            ax.add_collection(LineCollection(segments, colors="#c85a00", linewidths=1.2))
            legend_items.append(("Interface geologique", "#c85a00"))

    if plot_config.show_river_edges:
        segments = _build_edge_segments(
            mesh,
            selector=lambda edge: bool(edge.is_river),
        )
        if segments:
            ax.add_collection(LineCollection(segments, colors="#1f78b4", linewidths=1.1))
            legend_items.append(("Riviere", "#1f78b4"))

    if legend_items:
        from matplotlib.lines import Line2D

        ax.add_artist(
            ax.legend(
                handles=[
                    Line2D([0], [0], color=color, lw=1.1, label=label)
                    for label, color in legend_items
                ],
                loc="lower left",
                fontsize=9,
                framealpha=0.95,
                title="Surcouches",
                title_fontsize=10,
            )
        )


def _plot_cell_annotations(
    ax,
    *,
    mesh: MeshBundleLike,
    plot_config: PlotConfig,
) -> None:
    """Ajoute les ids de cellules si l'option est activee."""
    if not plot_config.annotate_cell_ids:
        return

    for cell in mesh.cells:
        ax.text(
            float(cell.centroid_x),
            float(cell.centroid_y),
            str(cell.cell_id),
            ha="center",
            va="center",
            fontsize=7,
            color="0.15",
        )


def _plot_mesh_panel(
    ax,
    *,
    mesh: MeshBundleLike,
    plot_config: PlotConfig,
    color_field: str,
    color_map: str,
    title: str,
    show_info_box: bool,
    matplotlib,
    plt,
    LineCollection,
    PolyCollection,
    Patch,
) -> None:
    """Construit un panneau base sur un coloriage par cellule.

    Ce panneau est la vue "structurelle" du maillage : on part des cellules,
    on les colorie, puis on ajoute les surcouches lineaires utiles a la lecture
    du resultat.
    """

    mesh_edge_color = str(plot_config.mesh_edge_color) if plot_config.show_mesh_edges else "none"
    mesh_edge_linewidth = (
        float(plot_config.mesh_edge_linewidth) if plot_config.show_mesh_edges else 0.0
    )
    polygons = _build_cell_polygons(mesh)

    # Le rendu depend du type de champ demande : numerique ou categoriel.
    if color_field in NUMERIC_COLOR_FIELDS:
        _plot_numeric_cells(
            ax,
            polygons=polygons,
            values=_get_numeric_cell_values(mesh, color_field),
            color_map=color_map,
            mesh_edge_color=mesh_edge_color,
            mesh_edge_linewidth=mesh_edge_linewidth,
            PolyCollection=PolyCollection,
            plt=plt,
        )
    else:
        _plot_categorical_cells(
            ax,
            polygons=polygons,
            values=_get_categorical_cell_values(mesh, color_field),
            color_map=color_map,
            mesh_edge_color=mesh_edge_color,
            mesh_edge_linewidth=mesh_edge_linewidth,
            matplotlib=matplotlib,
            PolyCollection=PolyCollection,
            Patch=Patch,
        )

    _plot_overlays(
        ax,
        mesh=mesh,
        plot_config=plot_config,
        LineCollection=LineCollection,
    )
    _plot_cell_annotations(
        ax,
        mesh=mesh,
        plot_config=plot_config,
    )

    node_xy_map = _build_node_xy_map(mesh)
    _format_axes(ax, node_xy_map=node_xy_map)
    ax.set_title(title)

    if show_info_box:
        ax.text(
            0.99,
            0.01,
            _build_info_text(mesh),
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


def _plot_continuous_topography_panel(
    ax,
    *,
    mesh: MeshBundleLike,
    plot_config: PlotConfig,
    color_map: str,
    title: str,
    plt,
    LineCollection,
) -> bool:
    """Construit un panneau topographique continu a partir des noeuds.

    Lorsque les altitudes `z_top` existent sur les noeuds, on peut construire
    un rendu bien plus proche d'un MNT qu'un simple coloriage par cellule.
    """
    from matplotlib import tri as mtri

    x_values, y_values, triangles = _build_triangulation_inputs(mesh)
    if not triangles:
        return False

    # On masque les triangles pour lesquels au moins un noeud n'a pas d'altitude.
    z_values, valid_mask = _get_node_topography_values(mesh)
    triangle_mask = [
        not bool(valid_mask[i0] and valid_mask[i1] and valid_mask[i2])
        for i0, i1, i2 in triangles
    ]
    if all(triangle_mask):
        return False

    triangulation = mtri.Triangulation(x_values, y_values, triangles)
    if any(triangle_mask):
        triangulation.set_mask(triangle_mask)

    # Le shading Gouraud donne un rendu plus proche d'un MNT continu.
    surface = ax.tripcolor(
        triangulation,
        z_values,
        cmap=color_map,
        shading="gouraud",
    )
    plt.colorbar(surface, ax=ax, fraction=0.04, pad=0.02)

    if plot_config.show_mesh_edges:
        ax.triplot(
            triangulation,
            color=str(plot_config.mesh_edge_color),
            linewidth=float(plot_config.mesh_edge_linewidth),
        )

    _plot_overlays(
        ax,
        mesh=mesh,
        plot_config=plot_config,
        LineCollection=LineCollection,
    )
    _plot_cell_annotations(
        ax,
        mesh=mesh,
        plot_config=plot_config,
    )

    node_xy_map = _build_node_xy_map(mesh)
    _format_axes(ax, node_xy_map=node_xy_map)
    ax.set_title(title)
    return True


def build_visualization_figure(
    mesh: MeshBundleLike,
    *,
    config: VisualizationConfig,
):
    """Construit la figure finale de visualisation.

    Le panneau de gauche montre le maillage et ses contraintes.
    Le panneau de droite montre une vue topographique type MNT si demandee.
    """

    matplotlib, plt, LineCollection, PolyCollection, Patch = _load_matplotlib(
        show_window=config.show_window
    )
    panel_count = 2 if config.plot.show_topography_panel else 1
    figure, axes = plt.subplots(
        1,
        panel_count,
        figsize=config.plot.figure_size,
        dpi=config.plot.dpi,
    )
    axes = [axes] if panel_count == 1 else list(axes)

    left_title = config.plot.title
    if left_title is None:
        left_title = (
            "Vue structurelle du maillage\n"
            f"color_field = {config.plot.color_field}"
        )

    _plot_mesh_panel(
        axes[0],
        mesh=mesh,
        plot_config=config.plot,
        color_field=config.plot.color_field,
        color_map=config.plot.color_map,
        title=left_title,
        show_info_box=True,
        matplotlib=matplotlib,
        plt=plt,
        LineCollection=LineCollection,
        PolyCollection=PolyCollection,
        Patch=Patch,
    )

    if config.plot.show_topography_panel:
        right_title = config.plot.topography_title
        if right_title is None:
            right_title = (
                "Vue topographique continue\n"
                f"topography_field = {config.plot.topography_field}"
            )

        has_continuous_render = _plot_continuous_topography_panel(
            axes[1],
            mesh=mesh,
            plot_config=config.plot,
            color_map=config.plot.topography_cmap,
            title=right_title,
            plt=plt,
            LineCollection=LineCollection,
        )

        # Si le bundle ne fournit pas assez d'altitudes nodales, on retombe
        # proprement sur un rendu par cellule pour ne pas bloquer l'outil.
        if not has_continuous_render:
            _plot_mesh_panel(
                axes[1],
                mesh=mesh,
                plot_config=config.plot,
                color_field=config.plot.topography_field,
                color_map=config.plot.topography_cmap,
                title=f"{right_title}\nrepli par cellule",
                show_info_box=False,
                matplotlib=matplotlib,
                plt=plt,
                LineCollection=LineCollection,
                PolyCollection=PolyCollection,
                Patch=Patch,
            )

    figure.tight_layout()
    return figure


__all__ = [
    "build_visualization_figure",
    "has_continuous_node_topography",
]

