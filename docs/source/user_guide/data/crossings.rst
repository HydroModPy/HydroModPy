Crossings
=========

``crossings`` loads the structures laid across the channels: roads and
railways on embankments, bridges, weirs and dams. A DEM shows an embankment as
a wall across the valley, and the routing chain then fills behind it or digs
through it. The variable says where these structures are, so that the ground
can be corrected at the crossings and nowhere else.

The variable only declares the structures. What the geographic step does with
them is set in ``[geographic.crossings]``, which reads the file this variable
resolves when its own ``path`` is left empty.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 18 42 40

   * - Source
     - Use when
     - Payload
   * - ``bdtopo``
     - The French IGN BD TOPO is the reference for roads and railways.
     - Lines, from the Geoplateforme WFS.
   * - ``roe``
     - The Sandre ROE (Referentiel des Obstacles a l'Ecoulement) is the
       reference for weirs, dams and bridge sills.
     - Points, from the Sandre WFS.
   * - ``custom``
     - Your own survey or a national dataset outside France.
     - A vector file with a ``kind`` column.

Sources add up: declare several blocks and the records are merged. The complete
``[[data.crossings.sources]]`` schema is in :doc:`the data reference
<../config_reference/data>`.

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["crossings"]

   [[data.crossings.sources]]
   source = "bdtopo"

   [[data.crossings.sources]]
   source = "roe"

Loaded shape
------------

Every source answers with one GeoDataFrame in the project CRS and the same
columns.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Column
     - Content
   * - ``geometry``
     - A line for a road or a railway, a point for an obstacle.
   * - ``kind``
     - ``road``, ``railway``, ``bridge``, ``weir``, ``dam`` or ``other``.
   * - ``source``
     - ``bdtopo``, ``roe`` or ``custom``.
   * - ``name``
     - What the provider calls the structure, an empty string when it says
       nothing.
   * - ``drop_m``
     - The drop of a weir or a dam in metres, NaN when unknown.

BD TOPO
-------

The layers are ``BDTOPO_V3:troncon_de_route`` and
``BDTOPO_V3:troncon_de_voie_ferree``, asked over a Lambert-93 box and counted
against the total the server announces. The licence is the Licence Ouverte
Etalab 2.0.

What the layers say about a structure was measured on the live service over the
upper Ille and Rennes:

- ``position_par_rapport_au_sol`` is a signed integer. ``0`` is on the ground
  (98 % of the segments). ``1`` and ``2`` are above it, a bridge or a viaduct,
  and ``-1`` and ``-2`` are below it, a tunnel.
- The road layer has no attribute for a culvert. A road over a culvert is a
  ground segment, so a culvert cannot be told from an embankment in this data.
- Only segments ``En service`` are kept, and a ``fictif`` one is dropped.
  Stairs and ferries lay nothing across a channel and are dropped too.

So a segment above the ground is a ``bridge``, a segment below it is ``other``
(a tunnel leaves the surface alone), and the rest is a ``road`` or a
``railway`` by its layer. Footpaths and tracks stay roads: filter them out with
a ``custom`` file if they should not count.

ROE
---

The layer is ``sa:ObstEcoul_FXX`` of the Sandre, one point per obstacle, and
it answers GML only. Only obstacles whose state is ``Existant`` are kept.

``CdTypeOuvrage`` is a hierarchy and a leaf carries its parents, so the kind is
read from its first two levels:

.. list-table::
   :header-rows: 1
   :widths: 28 22 50

   * - ``CdTypeOuvrage``
     - ``kind``
     - Meaning
   * - ``1.1``, ``1.1.7``
     - ``dam``
     - Barrage and its subtypes.
   * - ``1.2``, ``1.2.1``, ``1.2.X``
     - ``weir``
     - Seuil en riviere and its subtypes.
   * - ``1.4``, ``1.4.1``
     - ``weir``
     - Obstacle induit par un pont: the sill under a bridge, a drop of the bed
       that is kept, not an embankment. A bridge deck comes from the BD TOPO.
   * - anything else
     - ``other``
     - A dike (``1.3``), a groyne (``1.5``), a fish farm grid (``1.6``) or an
       obstacle with no code.

``drop_m`` is ``HautChutEtObstEcoul``, the drop in metres. Most obstacles leave
it empty and carry only a class of drop, which is not a height, so they stay
NaN. ``name`` is ``NomPrincipalObstEcoul``.

Custom file
-----------

A vector file (SHP, GPKG, GeoJSON), or a folder holding one, with a ``kind``
column. A file without it is refused by name, and so is a ``kind`` outside the
six values: a structure of unknown kind cannot be told from one the notch must
leave alone. ``name`` and ``drop_m`` are read when present.

.. code-block:: toml

   [[data.crossings.sources]]
   source = "custom"
   path = "data/crossings/crossings_custom_my_roads.gpkg"

The extent
----------

:ref:`mask_path <data-crossings-mask-path>` is the file whose bounds are the
box the two downloading sources are asked over. It sits on the section because
every source is asked over the same box. A project run leaves it empty and the
delineated watershed is filled in. Features come whole: a road that leaves the
box is not cut.

Files on disk
-------------

A download lands in the data folder of the workspace
(``<workspace>/data/crossings/``) as ``crossings_<source>_<box hash>.gpkg``, in
Lambert-93, and the catalogue serves it back for any box it contains. A
``custom`` file is normalised into a GeoParquet copy under
``data/blobs/crossings/custom/``, never next to the file you dropped.

The geographic step cannot wait for the data managers. It resolves the
declaration itself, over a box of 30 km around the outlet clipped to the DEM
footprint, and writes **one** file holding every source merged:
``crossings_ground_<sources>_<key>.gpkg``, in the project CRS. That file is not
registered in the catalogue. Its key hashes the box, the CRS and every source,
a custom file by its path, size and modification time, so a changed input is a
new file.

Before the DEM footprint is known, that box holds a lot: the BD TOPO counts
about 210 000 road segments in a 60 km box around Rennes. The pages are written
to the file as they arrive and only the attributes the variable reads are asked
for, so memory holds one page, but the download itself still takes minutes. The
log gives the feature count and the time of each source.

Operational checks
------------------

- Check that the CRS of a ``custom`` file is declared. A file without one is
  read in ``default_crs``, Lambert-93 unless you set it.
- Look at ``kind`` counts in the log line of the resolver before enabling the
  notch: a catchment with no bridge and many roads is plausible, one with no
  road at all is not.
- Obstacles in the ROE are points. They only matter where a channel passes
  within the snap radius of the notch.

Downstream uses
---------------

- the crossing notches of the ground, set in ``[geographic.crossings]``;
- weirs, as a drop of the stream bed, where the network reads them.

The notch
---------

``[geographic.crossings]`` turns the structures of this variable into a
correction of the ground. Roads, railways and bridges are the kinds it notches
(``kinds``); weirs and dams never are, and a crossing at a declared dam or weir
is left alone. Where a line structure crosses the
channel tree that the DEM generates, or where a point structure lies within
``snap_radius`` of it, the embankment pixels on the channel are lowered to the
straight line between the bed levels read ``bed_reach`` upstream and downstream.
Nothing is raised, nothing is lowered by more than ``max_depth``, and the
catchment is delineated again on the notched ground. The :ref:`ground section of
the DEM page <the-ground>` gives the whole sequence and the report it writes.

.. code-block:: toml

   [data]
   types = ["dem", "crossings"]

   [[data.crossings.sources]]
   source = "bdtopo"

   [[data.crossings.sources]]
   source = "roe"

   [geographic.river_network]
   enabled = true
   threshold_area_km2 = 0.5

   [geographic.crossings]
   enabled = true

``path`` is left empty so the resolver above fills it. Declare it only to notch a
file that differs from the one the data variable loads. Enabled with neither a
``path`` nor a source is refused at the start of the run, and so is a notch with
``[geographic.river_network]`` disabled.
