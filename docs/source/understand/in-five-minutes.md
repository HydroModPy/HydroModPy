# In five minutes

One map, five sentences. If you read nothing else, read this page.

```{figure} /_static/figures/understand/ex04_flow_intermittence_map.webp
:alt: Map of the Nançon catchment for the year 2002. Perennial streams in blue form a trunk and its main branches. Intermittent streams in orange are at the upstream ends and on side branches. The rest of the catchment is dry, in gray.
:width: 75%

{bdg-warning}`Indicative` **Look at:** the blue trunk that flows all year and the orange ends that dry up first.
**Does not show:** which reaches dry up in the field, or any other year.

`flow_intermittence_map`, year 2002, demonstration model of example 04.
```

1. HydroModPy computes, for a whole catchment and for each month, the level of the
   {term}`groundwater` under the ground, from the relief, the properties of the rock and the
   rain that reaches the water table.
2. Where that level reaches the ground, water comes out: these points are the {term}`springs
   <spring>` of the model.
3. The streams are what these springs feed downhill. On the map, a stream is blue when it flows
   all year, orange when it flows part of the year, and grey when it never flows.
4. This map is a demonstration, not a study of the catchment: it was not compared with
   observations of dry reaches, so it is labelled *indicative*. Other results carry the labels
   *calibrated* or *numerical check*, and the label says how far to trust them
   ({term}`reliability label`).
5. Every result depends on assumptions and on data, so read its caption, its label and the
   limits before you decide anything with it.

## Where to go next

- To know what the model computes and what it leaves out: {doc}`what-it-computes`.
- To read each map and curve: {doc}`reading-results`.
- To know how far a result can be wrong: {doc}`how-sure`.
- To know when not to use the model: the end of the {doc}`door index <index>`.
