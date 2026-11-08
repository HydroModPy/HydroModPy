"""Administrative boundaries, for France only.

The ``france`` module reads the bundled outlines of the departments
(metropolitan and overseas, about 600 KB) and answers locally, without a
network call. :func:`france.find_departments_in_bbox` gives the departments a
rectangle touches, :func:`france.find_departments_in_regions` the departments
of a region, :func:`france.bbox_for_departments` and
:func:`france.bbox_for_regions` their bounding box, and
:func:`france.geometry_for_departments` and :func:`france.geometry_for_regions`
the union of their outlines. Callers import ``france`` by name.
"""
