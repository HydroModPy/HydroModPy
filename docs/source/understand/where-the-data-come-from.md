# Where the data come from

A result is only as good as its inputs. This page names the data that HydroModPy can read, who
produces them, how fine they are, and what to do about their licences. It is written for a reader
who must judge a result, not for one who must download data: that task is the guide
{doc}`../guides/get-the-data`.

## What the model reads

The model reads its data from files that you give it, or from public providers that it can
download from. Example 04 uses files of the project. The last column says what it used.

| Data | Producer | Form and fineness | Example 04 |
|---|---|---|---|
| Relief ({term}`digital elevation model`) | The national mapping agency (IGN): BD ALTI at 25 m, or RGE ALTI at 1 m or 5 m | Regular grid | A raster file with 75 m cells |
| Geological map | The geological survey (BRGM): a map at 1:1,000,000, or the harmonised map at 1:50,000 | Polygons, with the scale of the map as limit | Not used: one value of K for the catchment |
| Mapped streams | Sandre and the French Biodiversity Office ({term}`BD Topage`); the Copernicus land service (EU-Hydro); OpenStreetMap. A file of your own works too, such as the {term}`BD TOPO` of IGN | Lines | The permanent reaches of the BD TOPO, from a file of the project |
| Discharge at a gauge | The public interface {term}`Hub'Eau` (French Biodiversity Office and BRGM), for the national hydrometry | Daily series at a station | The {term}`NANCON station`, averaged by month |
| Observed flow state of small streams | Hub'Eau, from the national low-flow observatory | Visits at stations | Not used |
| Groundwater levels | Hub'Eau, from the national portal for groundwater data (ADES) | Series at wells | Not used |
| Rain and evapotranspiration | Météo-France, the {term}`SIM2` reanalysis | 8 km grid | The recharge and the runoff are series given as files of the project |
| Climate projections | Météo-France, distributed through the DRIAS portal (Explore2) | 8 km grid | Not used |
| Sea level | The naval hydrographic service (SHOM), tide gauges | Series at a gauge | Not used |

This list is read from the data sources that the code knows. The generated page
{doc}`/reference/data-sources` gives the complete list of the sources, the producer of each and
the section of the file that takes it.

## Fineness matters

Each input has its own scale, and the model cannot be finer than the inputs that control a
result.

- The rain comes on an 8 km grid. The catchment of example 04 is 64.6 km², so a few grid points
  cover it. In example 04, one monthly recharge series serves the whole catchment: no difference
  between two hillsides.
- The relief sets where water leaves the ground, and the cell of the model is 75 m. A map is read
  at the scale of the hillside ({term}`resolution`).
- A geological map at 1:50,000 draws zones that are hundreds of metres wide. It does not tell the
  conductivity of a particular field.
- A mapped stream network draws what someone chose to draw, with a positional error. The score
  of a network takes it into account only if that error is declared ({doc}`network-metrics`).

## Licences

Public data do not all carry the same licence. The licence of each source, when the code knows
it, is listed on the generated page {doc}`/reference/data-sources`. Where the code does not know
it, the page says so. It does not guess.

Three rules follow from the way the code records licences.

- **A file you provide has the licence you declare.** The model cannot know the licence of your
  file. You state it in a small companion file next to the data.
- **A result inherits from its inputs.** A run states the combined licence of what it read, and
  writes it into the attributes of its field files and the footers of its tables. If one input has
  no known licence, the run states *undetermined*. A run cannot promise more than its least known
  input allows.
- **Undetermined is not forbidden.** It means that nobody recorded the terms. Read the terms of
  the producer before you reuse or redistribute a result.

This page is not legal advice. Cite the producer of the data that a result relies on.

## Can I check which data were used?

Yes. Each run lists its input files with their checksums, and the project can pin the whole data
cache. See {doc}`can-i-check-what-was-run`.

## Where to go next

- {doc}`/reference/data-sources`: every source, its producer and its licence.
- {doc}`../guides/get-the-data`: declare or download the data of a project.
- {doc}`what-validated-means`: why a good input is not a validated result.
