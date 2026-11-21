"""The land cover pivot: the ESA CCI legend, its GCN250 curve numbers, and the crosswalks.

No official correspondence links OCS GE, Corine Land Cover and ESA WorldCover, and no
pivot legend is recognized in hydrology. The one published bridge from land cover to a
hydrological table is GCN250 (Jaafar, Ahmad and El Beyrouthy 2019, Scientific Data 6:145):
each class of the ESA CCI legend is split into plant functional types, each type takes a
row of NEH-630, and the class gets a curve number for each hydrologic soil group. So the
pivot is the ESA CCI legend itself, and every class of another legend points to exactly
one CCI class: each curve number used is a published row, never a mean we made. The
crosswalks are ours and say why beside each choice.

Three rules hold for every legend. A sealed or built-up class points to nothing, since
``[data.impervious]`` runs the sealed ground off whole and the curve number applies to
the unsealed share only. Water and snow point to nothing, since GCN250 gives them no
curve number. Managed meadows point to CCI 11, herbaceous cover, whose row is the
managed grass of GCN250 (57/68/75/78), not to CCI 130, grassland, which GCN250 splits
into 60 % natural grass and 40 % bare soil (54/71/81/86) and which would make a meadow
run off more than a field.

The table is plain dicts, so a configuration that names a legend loads no library.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CciClass:
    """One class of the ESA CCI legend and its GCN250 curve numbers for soil groups A to D."""

    label: str
    curve_numbers: tuple[int, int, int, int] | None  # AMC II, Ia = 0.2 S; None: no runoff law


CCI_CLASSES: dict[int, CciClass] = {
    10: CciClass("Cropland, rainfed", (57, 68, 75, 78)),
    11: CciClass("Herbaceous cover", (57, 68, 75, 78)),
    12: CciClass("Tree or shrub cover", (49, 65, 75, 79)),
    20: CciClass("Cropland, irrigated or post-flooding", (61, 71, 77, 80)),
    30: CciClass(
        "Mosaic cropland (>50%)/natural vegetation (tree, shrub, herbaceous cover) (<50%)",
        (49, 64, 74, 79),
    ),
    40: CciClass(
        "Mosaic natural vegetation (tree, shrub, herbaceous cover) (>50%)/cropland (<50%)",
        (46, 63, 74, 79),
    ),
    50: CciClass("Tree cover, Br., Ev., closed to open (>15%)", (31, 56, 70, 77)),
    60: CciClass("Tree cover, Br., De., closed to open (>15%)", (35, 59, 72, 79)),
    61: CciClass("Tree cover, Br., De., closed (>40%)", (35, 59, 72, 79)),
    62: CciClass("Tree cover, Br., De., open (15-40%)", (42, 63, 75, 81)),
    70: CciClass("Tree cover, Ne., Ev., closed to open (>15%)", (35, 59, 72, 79)),
    71: CciClass("Tree cover, Ne., Ev., closed (>40%)", (35, 59, 72, 79)),
    72: CciClass("Tree cover, Ne., Ev., open (15-40%)", (49, 68, 78, 84)),
    80: CciClass("Tree cover, Ne., De., closed to open (>15%)", (44, 64, 76, 82)),
    81: CciClass("Tree cover, Ne., De., closed (>40%)", (44, 64, 76, 82)),
    82: CciClass("Tree cover, Ne., De., open (15-40%)", (53, 70, 80, 85)),
    90: CciClass("Tree cover, mixed leaf type (Br. and Ne.)", (41, 62, 75, 81)),
    100: CciClass("Mosaic tree & shrub (>50%)/herbaceous cover (<50%)", (37, 60, 73, 79)),
    110: CciClass("Mosaic herbaceous cover (>50%)/tree & shrub (<50%)", (38, 60, 73, 80)),
    120: CciClass("Shrubland", (48, 66, 77, 83)),
    121: CciClass("Evergreen shrubland", (48, 65, 77, 83)),
    122: CciClass("Deciduous shrubland", (48, 67, 78, 83)),
    130: CciClass("Grassland", (54, 71, 81, 86)),
    140: CciClass("Lichens and mosses", (54, 71, 81, 86)),
    150: CciClass("Sparse vegetation (tree, shrub, herbaceous cover) (<15%)", (71, 82, 88, 92)),
    152: CciClass("Sparse shrub (<15%)", (72, 82, 88, 92)),
    153: CciClass("Sparse herbaceous cover (<15%)", (71, 82, 88, 92)),
    160: CciClass("Tree cover, flooded, fresh or brackish water", (47, 66, 77, 83)),
    170: CciClass("Tree cover, flooded, saline water", (46, 65, 76, 82)),
    180: CciClass(
        "Shrub or herbaceous cover, flooded, fresh/saline/brackish water", (57, 72, 82, 86)
    ),
    190: CciClass("Urban areas", (70, 82, 88, 91)),
    200: CciClass("Bare areas", (77, 86, 91, 94)),
    201: CciClass("Consolidated bare areas", (85, 90, 93, 94)),
    202: CciClass("Unconsolidated bare areas", (77, 86, 91, 94)),
    210: CciClass("Water bodies", None),
    220: CciClass("Permanent snow and ice", None),
}
"""The ESA CCI classes and their curve numbers, Online-only Table 1 of Jaafar et al. (2019)."""

SOIL_GROUPS = ("A", "B", "C", "D")
HYSOGS_CODES: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3, 11: 3, 12: 3, 13: 3, 14: 3}
"""HYSOGs250m pixel value to the column of a soil group (Ross et al. 2018, ORNL DAAC 1566).

11 to 14 are the dual groups A/D to D/D of soils with a water table within 60 cm. They read
as D, high runoff potential unless drained, as GCN250 does.
"""

LEFT_OUT = 0
"""A crosswalk value that leaves a class out of the curve number map (CCI 0 is no data)."""

WORLDCOVER_TO_CCI: dict[str, int] = {
    "10": 90,  # tree cover, leaf type not mapped: the mixed leaf type row
    "20": 120,  # shrubland
    "30": 130,  # grassland, natural by WorldCover's definition; a meadow region overrides it to 11
    "40": 10,  # cropland
    "50": LEFT_OUT,  # built-up: [data.impervious]
    "60": 200,  # bare / sparse vegetation, under 10 % plant cover
    "70": LEFT_OUT,  # snow and ice
    "80": LEFT_OUT,  # permanent water bodies
    "90": 180,  # herbaceous wetland
    "95": 170,  # mangroves
    "100": 140,  # moss and lichen
}

CLC_TO_CCI: dict[str, int] = {
    "111": LEFT_OUT,  # continuous urban fabric: [data.impervious]
    "112": LEFT_OUT,  # discontinuous urban fabric: [data.impervious]
    "121": LEFT_OUT,  # industrial or commercial units
    "122": LEFT_OUT,  # road and rail networks
    "123": LEFT_OUT,  # port areas
    "124": LEFT_OUT,  # airports
    "131": 200,  # mineral extraction sites
    "132": 200,  # dump sites
    "133": 200,  # construction sites
    "141": 11,  # green urban areas, managed grass
    "142": 11,  # sport and leisure facilities, managed grass
    "211": 10,  # non-irrigated arable land
    "212": 20,  # permanently irrigated land
    "213": 20,  # rice fields
    "221": 12,  # vineyards
    "222": 12,  # fruit trees and berry plantations
    "223": 12,  # olive groves
    "231": 11,  # pastures, managed grass
    "241": 10,  # annual crops associated with permanent crops
    "242": 10,  # complex cultivation patterns
    "243": 30,  # agriculture with significant natural vegetation: mosaic cropland
    "244": 12,  # agro-forestry areas
    "311": 60,  # broad-leaved forest, deciduous in Europe
    "312": 70,  # coniferous forest, evergreen
    "313": 90,  # mixed forest
    "321": 130,  # natural grassland
    "322": 120,  # moors and heathland
    "323": 121,  # sclerophyllous vegetation, evergreen shrubs
    "324": 100,  # transitional woodland-shrub
    "331": 202,  # beaches, dunes, sands
    "332": 201,  # bare rocks
    "333": 150,  # sparsely vegetated areas
    "334": 150,  # burnt areas
    "335": LEFT_OUT,  # glaciers and perpetual snow
    "411": 180,  # inland marshes
    "412": 180,  # peat bogs
    "421": 180,  # salt marshes
    "422": LEFT_OUT,  # salines
    "423": LEFT_OUT,  # intertidal flats
    "511": LEFT_OUT,  # water courses
    "512": LEFT_OUT,  # water bodies
    "521": LEFT_OUT,  # coastal lagoons
    "522": LEFT_OUT,  # estuaries
    "523": LEFT_OUT,  # sea and ocean
}

OCSGE_TO_CCI: dict[str, int] = {
    "CS1.1.1": LEFT_OUT,  # sealed: built (CS1.1.1.1) and unbuilt (CS1.1.1.2), [data.impervious]
    "CS1.1.2.1": 202,  # mineral materials, gravel and quarries: unconsolidated bare
    "CS1.1.2.2": 200,  # other composite materials
    "CS1.2.1": 200,  # bare soil, sand, loose stones, rock
    "CS1.2.2": LEFT_OUT,  # water surfaces
    "CS1.2.3": LEFT_OUT,  # firn and glaciers
    "CS2.1.1.1": 60,  # broadleaf stands, deciduous in France
    "CS2.1.1.2": 70,  # conifer stands, evergreen
    "CS2.1.1.3": 90,  # mixed stands
    "CS2.1.2": 120,  # shrub formations and heaths
    "CS2.1.3": 12,  # other woody formations, vines and orchards: tree or shrub crop
    "CS2.2.1": 11,  # herbaceous formations, arable land and meadows alike: managed grass
    "CS2.2.2": 140,  # other non-woody formations, lichens and mosses
}

CROSSWALKS: dict[str, dict[str, int]] = {
    "cci": {str(code): (LEFT_OUT if code == 190 else code) for code in CCI_CLASSES},
    "worldcover": WORLDCOVER_TO_CCI,
    "clc": CLC_TO_CCI,
    "ocsge": OCSGE_TO_CCI,
}
"""Each legend to the pivot, by the name a section writes. CCI 190, urban, is left to
[data.impervious] like every sealed class."""


def pivot_of(code: str, crosswalk: dict[str, int]) -> int | None:
    """The CCI class of ``code``: the longest key that starts it, None when no key does.

    OCS GE codes nest (CS2.1.1.1 under CS2.1), so a key holds every code it starts; the
    numeric codes of the other legends match whole.
    """
    if code in crosswalk:
        return crosswalk[code]
    if not code.startswith("CS"):
        return None
    keys = [key for key in crosswalk if key.startswith("CS") and code.startswith(key)]
    return crosswalk[max(keys, key=len)] if keys else None


def curve_number(cci: int, soil_group: int) -> int | None:
    """The GCN250 curve number of CCI class ``cci`` on soil group ``soil_group`` (0 to 3)."""
    found = CCI_CLASSES.get(cci)
    if found is None or found.curve_numbers is None:
        return None
    return found.curve_numbers[soil_group]


__all__ = [
    "CCI_CLASSES",
    "CLC_TO_CCI",
    "CROSSWALKS",
    "HYSOGS_CODES",
    "LEFT_OUT",
    "OCSGE_TO_CCI",
    "SOIL_GROUPS",
    "WORLDCOVER_TO_CCI",
    "CciClass",
    "curve_number",
    "pivot_of",
]
