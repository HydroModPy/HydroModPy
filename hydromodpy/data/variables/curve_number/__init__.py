"""The SCS curve number, read by the soil reservoir as a map.

A source is either a curve number raster (the user's file, a url, GCN250) or a land cover
(a raster of a named legend, ESA WorldCover, OCS GE) sent to the ESA CCI pivot of
``data/common/land_cover.py`` and read in the GCN250 table on the soil group the section
gives.
"""
