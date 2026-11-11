# display/quicklook

A quick look at data, outside the figure catalogue and unrelated to `hmp show --figure`.

| file | what it does |
|---|---|
| `viz.py` | `show(data)`: draws an xarray array as an image, a pandas series as a line, a GeoDataFrame as a map |
| `scalable.py` | the datashader rasterization `show` uses on a large array, when datashader is installed |
| `animation.py` | a GIF, an MP4 or a plotly slider made from PNG frames already drawn |

`show` is reached as `hydromodpy.viz.show`. A large series is thinned by LTTB
(`hydromodpy.results.derive.downsample`) and a large array is rasterized, so a
dense result still opens quickly. Datashader is an optional dependency (the `viz`
extra); without it an array is drawn at full resolution. The MP4 needs ffmpeg
behind imageio.
