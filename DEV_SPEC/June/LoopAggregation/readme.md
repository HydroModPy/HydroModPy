# Loop Aggregation

## Description


[[_TOC_]]


## How to install


## How to Run


## How to Use Loop Aggregation

### Description



#### settings_model.py

Parameters:
- site: number of the site to run the simulation for. The list of the different sites is located in `docker-simulation/modflow/data/study_sites.txt`.
- `-approx`: the number of the type of approximation. By default, use the approximation `0` as it corresponds to the mean function used as the aggregation function.
- `-chr`: number of the chronicle to use.
- `-rate`: the value of the aggregation parameter (i.e., to what extent to aggregate the values).
- `-ref`: to specify that the simulation to run is the reference simulaiton (i.e., no aggregation performed).



### Examples

#### Generate the input file for the corresponding Aggregation rate:

In folder `docker-simulation/modflow/custom_utils`:

```bash
python InputFileManipulation.py -rate $rate -chr $chronicle -approx $approximation
```

#### Run the corresponding modflow simulation

```bash
python3 settings_model.py -site $SITE -approx $APPROX -chr $CHR -rate $RATE ${REF} -rep $REP
```

