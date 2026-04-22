import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema
import sqlalchemy as db
from io import StringIO
from tqdm import tqdm
import xarray as xr
import numpy as np
import os
import shapely
from shapely import wkt as shapely_wkt
import matplotlib.pyplot as plt
from shapely.plotting import plot_polygon


class DatabaseTool:

    def __init__(self, testmode=False):
        self.__host = 'ns324.evxonline.net'
        self.__user = 'postgres'
        self.__password = '8jC56guc8KVKv3t9vW3R'
        self.__port = '5432'
        self.database = 'test_db' if testmode else 'waterwise-db'

    def get_engine(self):
        return create_engine(
            f'postgresql+psycopg2://{self.__user}:{self.__password}@{self.__host}:{self.__port}/{self.database}',
            connect_args={
                'keepalives':          1,
                'keepalives_idle':     60,
                'keepalives_interval': 10,
                'keepalives_count':    5,
                'options':             '-c statement_timeout=0'
            }
        )


    # -------------------------------------------------------------------------
    # Schema
    # -------------------------------------------------------------------------

    def setup_schema(self):
        """Create the climate schema with t_models, monthly_mean, yearly_mean and daily_mean tables.
        Safe to run multiple times (uses IF NOT EXISTS).

        Tables created:
            climate.t_models     -- model registry
            climate.daily_mean   -- spatially averaged daily values per site/model (from CSV)
            climate.monthly_mean -- spatially averaged monthly values per site/model (from NetCDF)
            climate.yearly_mean  -- spatially averaged yearly values per site/model (from NetCDF)
        """
        engine = self.get_engine()

        inspector = db.inspect(engine)
        if 'climate' not in inspector.get_schema_names():
            with engine.connect() as conn:
                conn.execute(CreateSchema('climate', if_not_exists=True))
                conn.commit()

        with engine.connect() as conn:

            conn.execute(db.text("""
                CREATE TABLE IF NOT EXISTS climate.t_models (
                    id_model    SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL UNIQUE,
                    description TEXT
                );
            """))

            conn.execute(db.text("""
                CREATE TABLE IF NOT EXISTS climate.daily_mean (
                    time     TIMESTAMPTZ NOT NULL,
                    id_site  INT NOT NULL REFERENCES sites.t_sites(id_site),
                    id_model INT NOT NULL REFERENCES climate.t_models(id_model),
                    precip   FLOAT4,
                    runoff   FLOAT4,
                    evapo    FLOAT4,
                    rechg    FLOAT4
                );
            """))
            conn.execute(db.text("""
                SELECT create_hypertable('climate.daily_mean', 'time',
                    partitioning_column => 'id_site',
                    number_partitions   => 16,
                    chunk_time_interval => INTERVAL '1 year',
                    if_not_exists       => TRUE);
            """))
            conn.execute(db.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_mean_unique
                ON climate.daily_mean (id_site, id_model, time);
            """))
            conn.execute(db.text("""
                CREATE INDEX IF NOT EXISTS idx_daily_mean_lookup
                ON climate.daily_mean (id_site, id_model, time DESC);
            """))
            conn.execute(db.text("""
                ALTER TABLE climate.daily_mean
                SET (timescaledb.enable_columnstore = true);
            """))
            conn.execute(db.text("""
                SELECT add_compression_policy('climate.daily_mean',
                    INTERVAL '2 years', if_not_exists => TRUE);
            """))

            conn.execute(db.text("""
                CREATE TABLE IF NOT EXISTS climate.monthly_mean (
                    time     TIMESTAMPTZ NOT NULL,
                    id_site  INT NOT NULL REFERENCES sites.t_sites(id_site),
                    id_model INT NOT NULL REFERENCES climate.t_models(id_model),
                    precip   FLOAT4,
                    runoff   FLOAT4,
                    evapo    FLOAT4,
                    rechg    FLOAT4
                );
            """))
            conn.execute(db.text("""
                SELECT create_hypertable('climate.monthly_mean', 'time',
                    partitioning_column => 'id_site',
                    number_partitions   => 16,
                    chunk_time_interval => INTERVAL '10 years',
                    if_not_exists       => TRUE);
            """))
            conn.execute(db.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_monthly_mean_unique
                ON climate.monthly_mean (id_site, id_model, time);
            """))
            conn.execute(db.text("""
                CREATE INDEX IF NOT EXISTS idx_monthly_mean_lookup
                ON climate.monthly_mean (id_site, id_model, time DESC);
            """))
            conn.execute(db.text("""
                ALTER TABLE climate.monthly_mean
                SET (timescaledb.enable_columnstore = true);
            """))
            conn.execute(db.text("""
                SELECT add_compression_policy('climate.monthly_mean',
                    INTERVAL '2 years', if_not_exists => TRUE);
            """))

            conn.execute(db.text("""
                CREATE TABLE IF NOT EXISTS climate.yearly_mean (
                    time     TIMESTAMPTZ NOT NULL,
                    id_site  INT NOT NULL REFERENCES sites.t_sites(id_site),
                    id_model INT NOT NULL REFERENCES climate.t_models(id_model),
                    precip   FLOAT4,
                    runoff   FLOAT4,
                    evapo    FLOAT4,
                    rechg    FLOAT4
                );
            """))
            conn.execute(db.text("""
                SELECT create_hypertable('climate.yearly_mean', 'time',
                    partitioning_column => 'id_site',
                    number_partitions   => 16,
                    chunk_time_interval => INTERVAL '50 years',
                    if_not_exists       => TRUE);
            """))
            conn.execute(db.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_yearly_mean_unique
                ON climate.yearly_mean (id_site, id_model, time);
            """))
            conn.execute(db.text("""
                CREATE INDEX IF NOT EXISTS idx_yearly_mean_lookup
                ON climate.yearly_mean (id_site, id_model, time DESC);
            """))
            conn.execute(db.text("""
                ALTER TABLE climate.yearly_mean
                SET (timescaledb.enable_columnstore = true);
            """))
            conn.execute(db.text("""
                SELECT add_compression_policy('climate.yearly_mean',
                    INTERVAL '5 years', if_not_exists => TRUE);
            """))

            conn.commit()

        engine.dispose()
        print('Schema setup complete!')

    def delete_table(self, schema, table):
        """Drop a table.

        Args:
            schema (str): Schema name
            table (str): Table name
        """
        engine = self.get_engine()
        with engine.connect() as conn:
            conn.execute(db.text(f'DROP TABLE IF EXISTS {schema}.{table};'))
            conn.commit()
        engine.dispose()
        print(f'Dropped table: {schema}.{table}')


    # -------------------------------------------------------------------------
    # Model registry
    # -------------------------------------------------------------------------

    def register_model(self, name, description=''):
        """Insert a model into climate.t_models if it does not exist yet.

        Args:
            name (str): Model name (e.g. 'historic', '_cesm2')
            description (str): Optional description

        Returns:
            int: id_model
        """
        engine = self.get_engine()
        name = name.lower()
        with engine.connect() as conn:
            conn.execute(db.text("""
                INSERT INTO climate.t_models (name, description)
                VALUES (:name, :description)
                ON CONFLICT (name) DO NOTHING;
            """), {'name': name, 'description': description})
            conn.commit()
            row = conn.execute(
                db.text('SELECT id_model FROM climate.t_models WHERE name = :name'),
                {'name': name}
            ).fetchone()
        engine.dispose()
        return row[0]

    def get_model_id(self, name):
        """Get id_model for a given model name.

        Args:
            name (str): Model name

        Returns:
            int: id_model

        Raises:
            ValueError: If the model is not registered
        """
        engine = self.get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                db.text('SELECT id_model FROM climate.t_models WHERE name = :name'),
                {'name': name.lower()}
            ).fetchone()
        engine.dispose()
        if row is None:
            raise ValueError(f"Model '{name}' not found. Register it first with register_model().")
        return row[0]


    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_site_id(self, engine, site_label):
        """Look up id_site from sites.t_sites.
        Tries with '_' prefix if not already present.

        Returns:
            int | None
        """
        name = site_label if site_label.startswith('_') else '_' + site_label
        with engine.connect() as conn:
            row = conn.execute(
                db.text('SELECT id_site FROM sites.t_sites WHERE id_name = :id_name'),
                {'id_name': name}
            ).fetchone()
        return row[0] if row else None

    def _import_netcdf(self, file_path, id_site, id_model):
        """Read a help_example.out NetCDF, compute the spatial mean over all
        grid cells, and insert monthly rows into climate.monthly_mean.

        NetCDF structure (/data group):
            cid      (cell_dim,)                       -- cell IDs (used to detect cell dimension)
            years    (year_dim,)                       -- year values (used to detect year dimension)
            precip   (cell_dim, year_dim, month_dim)   -- 12 months
            runoff   (same)
            evapo    (same)
            rechg    (same)

        Dimensions are detected dynamically from cid and years so phony_dim
        numbering does not need to be assumed.

        NaN cells (flagged via idx_nan) are excluded from the mean automatically
        because xarray.mean() skips NaN by default.

        Args:
            file_path (str): Absolute path to help_example.out
            id_site (int): Site primary key
            id_model (int): Model primary key
        """
        engine = self.get_engine()

        # Skip if already imported
        with engine.connect() as conn:
            existing = conn.execute(db.text("""
                SELECT 1 FROM climate.monthly_mean
                WHERE id_site = :id_site AND id_model = :id_model
                LIMIT 1
            """), {'id_site': id_site, 'id_model': id_model}).fetchone()

        if existing:
            tqdm.write(f'    Already in DB (id_site={id_site}, id_model={id_model}), skipping.')
            engine.dispose()
            return

        # Fetch site boundary as WKT from PostGIS
        with engine.connect() as conn:
            row = conn.execute(db.text("""
                SELECT ST_AsText(geom) FROM sites.t_sites WHERE id_site = :id_site
            """), {'id_site': id_site}).fetchone()
        if row is None or row[0] is None:
            tqdm.write(f'    No boundary found for id_site={id_site}, skipping.')
            engine.dispose()
            return
        boundary = shapely_wkt.loads(row[0])

        ds   = xr.open_datatree(file_path, engine='h5netcdf', phony_dims='sort')
        data = ds['/data'].ds

        # Detect dimensions from 1-D reference variables instead of assuming
        # phony_dim_0/1/2 order (which depends on HDF5 sort order).
        cell_dim  = data['cid'].dims[0]    # e.g. phony_dim_0
        year_dim  = data['years'].dims[0]  # e.g. phony_dim_1
        years     = data['years'].values   # shape (n_years,)

        # Sanity check: month dimension should have size 12
        variables = ['precip', 'runoff', 'evapo', 'rechg']
        var_dims  = data[variables[0]].dims  # (cell_dim, year_dim, month_dim)
        month_dim = [d for d in var_dims if d not in (cell_dim, year_dim)][0]
        assert data.sizes[month_dim] == 12, (
            f'Expected 12 months in {month_dim}, got {data.sizes[month_dim]}')

        # Build a boolean mask: keep only cells whose centroid is inside the site boundary.
        # shapely.contains_xy vectorises the point-in-polygon test across all cells at once.
        lats = data['lat_dd'].values  # shape (n_cells,)
        lons = data['lon_dd'].values  # shape (n_cells,)
        mask = shapely.contains_xy(boundary, lons, lats)  # lon=x, lat=y
        n_inside = int(mask.sum())
        tqdm.write(f'    {n_inside}/{len(mask)} cells inside boundary.')
        if n_inside == 0:
            tqdm.write('    No cells inside boundary — check CRS or site geometry.')
            engine.dispose()
            return

        # Apply mask along cell_dim, then average — NaN cells skipped automatically.
        # monthly shape: (n_years, 12)  yearly shape: (n_years,)
        masked = {v: data[v].isel({cell_dim: np.where(mask)[0]}) for v in variables}
        monthly = {v: masked[v].mean(dim=cell_dim).transpose(year_dim, month_dim).values
                   for v in variables}
        yearly  = {v: masked[v].mean(dim=[cell_dim, month_dim]).values
                   for v in variables}

        # Monthly rows
        monthly_rows = []
        for yi, year in enumerate(years):
            for month in range(12):
                monthly_rows.append({
                    'time':     pd.Timestamp(year=int(year), month=month + 1, day=1, tz='UTC'),
                    'id_site':  id_site,
                    'id_model': id_model,
                    **{v: float(monthly[v][yi, month]) for v in variables}
                })

        # Yearly rows — timestamp is Jan 1 of each year
        yearly_rows = []
        for yi, year in enumerate(years):
            yearly_rows.append({
                'time':     pd.Timestamp(year=int(year), month=1, day=1, tz='UTC'),
                'id_site':  id_site,
                'id_model': id_model,
                **{v: float(yearly[v][yi]) for v in variables}
            })

        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            for df, table in [
                (pd.DataFrame(monthly_rows), 'monthly_mean'),
                (pd.DataFrame(yearly_rows),  'yearly_mean'),
            ]:
                buf = StringIO()
                df.to_csv(buf, index=False, header=False)
                buf.seek(0)
                cur.copy_expert(
                    f'COPY climate.{table} (time, id_site, id_model, precip, runoff, evapo, rechg)'
                    f' FROM STDIN WITH CSV',
                    buf
                )
            raw_conn.commit()
        finally:
            raw_conn.close()

        engine.dispose()


    def _import_daily_csv(self, file_path, id_site, id_model):
        """Read a help_example_daily_mean.csv and insert rows into climate.daily_mean.

        CSV format expected:
            column 0: date (YYYY-MM-DD)
            columns: precip, runoff, evapo, rechg

        Args:
            file_path (str): Absolute path to help_example_daily_mean.csv
            id_site (int): Site primary key
            id_model (int): Model primary key
        """
        engine = self.get_engine()

        # Skip if already imported
        with engine.connect() as conn:
            existing = conn.execute(db.text("""
                SELECT 1 FROM climate.daily_mean
                WHERE id_site = :id_site AND id_model = :id_model
                LIMIT 1
            """), {'id_site': id_site, 'id_model': id_model}).fetchone()

        if existing:
            tqdm.write(f'    Already in DB (id_site={id_site}, id_model={id_model}), skipping.')
            engine.dispose()
            return

        df = pd.read_csv(file_path, index_col=0, parse_dates=True)
        df.index.name = 'time'
        df.columns = ['precip', 'runoff', 'evapo', 'rechg']
        df = df.reset_index()
        df['time']     = pd.to_datetime(df['time'], utc=True)
        df['id_site']  = id_site
        df['id_model'] = id_model
        df = df[['time', 'id_site', 'id_model', 'precip', 'runoff', 'evapo', 'rechg']]

        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            buf = StringIO()
            df.to_csv(buf, index=False, header=False)
            buf.seek(0)
            cur.copy_expert(
                'COPY climate.daily_mean (time, id_site, id_model, precip, runoff, evapo, rechg)'
                ' FROM STDIN WITH CSV',
                buf
            )
            raw_conn.commit()
        finally:
            raw_conn.close()

        engine.dispose()


    # -------------------------------------------------------------------------
    # Import
    # -------------------------------------------------------------------------

    def import_historic(self, path):
        """Import historic data for all sites found in path.

        Expected structure:
            path/site_name/help_example.out

        Args:
            path (str): Path to the historic directory
        """
        engine  = self.get_engine()
        id_model = self.register_model('historic', 'Historic baseline run')

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Historic', unit='site'):

            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                tqdm.write(f"  Site '{site_label}' not found in sites.t_sites, skipping.")
                continue

            file_path = os.path.join(path, site_label, "results_pyhelp", 'help_example.out')
            if not os.path.isfile(file_path):
                tqdm.write(f'  [{site_label}] help_example.out not found, skipping.')
                continue

            tqdm.write(f'  [{site_label}] Importing...')
            self._import_netcdf(file_path, id_site, id_model)
            tqdm.write(f'  [{site_label}] Done!')

        engine.dispose()

    def import_prediction(self, path):
        """Import prediction data for all sites and models found in path.

        Expected structure:
            path/site_name/model_name/help_example.out

        Args:
            path (str): Path to the prediction directory
        """
        engine = self.get_engine()

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Prediction', unit='site'):

            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                tqdm.write(f"  Site '{site_label}' not found in sites.t_sites, skipping.")
                continue

            site_path = os.path.join(path, site_label)
            models    = [d for d in os.listdir(site_path) if os.path.isdir(os.path.join(site_path, d))]

            for model_label in tqdm(models, desc=f'  [{site_label}]', unit='model', leave=False):

                id_model  = self.register_model(model_label)
                file_path = os.path.join(site_path, model_label, 'help_example.out')

                if not os.path.isfile(file_path):
                    tqdm.write(f'  [{site_label} / {model_label}] help_example.out not found, skipping.')
                    continue

                tqdm.write(f'  [{site_label} / {model_label}] Importing...')
                self._import_netcdf(file_path, id_site, id_model)
                tqdm.write(f'  [{site_label} / {model_label}] Done!')

        engine.dispose()

    def import_historic_daily(self, path):
        """Import historic daily means for all sites found in path.

        Expected structure:
            path/site_name/help_example_daily_mean.csv

        Args:
            path (str): Path to the historic directory
        """
        engine  = self.get_engine()
        id_model = self.register_model('historic', 'Historic baseline run')

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Historic daily', unit='site'):

            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                tqdm.write(f"  Site '{site_label}' not found in sites.t_sites, skipping.")
                continue

            file_path = os.path.join(path, site_label, "results_pyhelp", 'help_example_daily_mean.csv')
            if not os.path.isfile(file_path):
                tqdm.write(f'  [{site_label}] help_example_daily_mean.csv not found, skipping.')
                continue

            tqdm.write(f'  [{site_label}] Importing daily...')
            self._import_daily_csv(file_path, id_site, id_model)
            tqdm.write(f'  [{site_label}] Done!')

        engine.dispose()

    def import_prediction_daily(self, path):
        """Import prediction daily means for all sites and models found in path.

        Expected structure:
            path/site_name/model_name/help_example_daily_mean.csv

        Args:
            path (str): Path to the prediction directory
        """
        engine = self.get_engine()

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Prediction daily', unit='site'):

            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                tqdm.write(f"  Site '{site_label}' not found in sites.t_sites, skipping.")
                continue

            site_path = os.path.join(path, site_label)
            models    = [d for d in os.listdir(site_path) if os.path.isdir(os.path.join(site_path, d))]

            for model_label in tqdm(models, desc=f'  [{site_label}]', unit='model', leave=False):

                id_model  = self.register_model(model_label)
                file_path = os.path.join(site_path, model_label, 'help_example_daily_mean.csv')

                if not os.path.isfile(file_path):
                    tqdm.write(f'  [{site_label} / {model_label}] help_example_daily_mean.csv not found, skipping.')
                    continue

                tqdm.write(f'  [{site_label} / {model_label}] Importing daily...')
                self._import_daily_csv(file_path, id_site, id_model)
                tqdm.write(f'  [{site_label} / {model_label}] Done!')

        engine.dispose()


    # -------------------------------------------------------------------------
    # Replace (delete + reimport)
    # -------------------------------------------------------------------------

    def replace_historic(self, path):
        """Delete existing historic data for all sites in path and re-import.

        Args:
            path (str): Path to the historic directory
        """
        engine = self.get_engine()

        try:
            id_model = self.get_model_id('historic')
        except ValueError:
            engine.dispose()
            self.import_historic(path)
            return

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Deleting historic', unit='site'):
            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                continue
            with engine.connect() as conn:
                r1 = conn.execute(db.text("""
                    DELETE FROM climate.monthly_mean
                    WHERE id_site = :id_site AND id_model = :id_model
                """), {'id_site': id_site, 'id_model': id_model})
                r2 = conn.execute(db.text("""
                    DELETE FROM climate.yearly_mean
                    WHERE id_site = :id_site AND id_model = :id_model
                """), {'id_site': id_site, 'id_model': id_model})
                conn.commit()
                tqdm.write(f'  [{site_label}] Deleted {r1.rowcount} monthly + {r2.rowcount} yearly rows.')

        engine.dispose()
        self.import_historic(path)

    def replace_prediction(self, path):
        """Delete existing prediction data for all sites and models in path and re-import.

        Args:
            path (str): Path to the prediction directory
        """
        engine = self.get_engine()

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Deleting predictions', unit='site'):
            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                continue

            site_path = os.path.join(path, site_label)
            models    = [d for d in os.listdir(site_path) if os.path.isdir(os.path.join(site_path, d))]

            for model_label in tqdm(models, desc=f'  [{site_label}]', unit='model', leave=False):
                try:
                    id_model = self.get_model_id(model_label)
                except ValueError:
                    continue
                with engine.connect() as conn:
                    r1 = conn.execute(db.text("""
                        DELETE FROM climate.monthly_mean
                        WHERE id_site = :id_site AND id_model = :id_model
                    """), {'id_site': id_site, 'id_model': id_model})
                    r2 = conn.execute(db.text("""
                        DELETE FROM climate.yearly_mean
                        WHERE id_site = :id_site AND id_model = :id_model
                    """), {'id_site': id_site, 'id_model': id_model})
                    conn.commit()
                    tqdm.write(f'  [{site_label} / {model_label}] Deleted {r1.rowcount} monthly + {r2.rowcount} yearly rows.')

        engine.dispose()
        self.import_prediction(path)

    def replace_historic_daily(self, path):
        """Delete existing historic daily data for all sites in path and re-import.

        Args:
            path (str): Path to the historic directory
        """
        engine = self.get_engine()

        try:
            id_model = self.get_model_id('historic')
        except ValueError:
            engine.dispose()
            self.import_historic_daily(path)
            return

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Deleting historic daily', unit='site'):
            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                continue
            with engine.connect() as conn:
                result = conn.execute(db.text("""
                    DELETE FROM climate.daily_mean
                    WHERE id_site = :id_site AND id_model = :id_model
                """), {'id_site': id_site, 'id_model': id_model})
                conn.commit()
                tqdm.write(f'  [{site_label}] Deleted {result.rowcount} rows.')

        engine.dispose()
        self.import_historic_daily(path)

    def replace_prediction_daily(self, path):
        """Delete existing prediction daily data for all sites and models in path and re-import.

        Args:
            path (str): Path to the prediction directory
        """
        engine = self.get_engine()

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site_label in tqdm(sites, desc='Deleting prediction daily', unit='site'):
            id_site = self._get_site_id(engine, site_label)
            if id_site is None:
                continue

            site_path = os.path.join(path, site_label)
            models    = [d for d in os.listdir(site_path) if os.path.isdir(os.path.join(site_path, d))]

            for model_label in tqdm(models, desc=f'  [{site_label}]', unit='model', leave=False):
                try:
                    id_model = self.get_model_id(model_label)
                except ValueError:
                    continue
                with engine.connect() as conn:
                    result = conn.execute(db.text("""
                        DELETE FROM climate.daily_mean
                        WHERE id_site = :id_site AND id_model = :id_model
                    """), {'id_site': id_site, 'id_model': id_model})
                    conn.commit()
                    tqdm.write(f'  [{site_label} / {model_label}] Deleted {result.rowcount} rows.')

        engine.dispose()
        self.import_prediction_daily(path)


    # -------------------------------------------------------------------------
    # Query / Export
    # -------------------------------------------------------------------------

    def get_monthly_mean(self, site, model=None):
        """Query monthly mean climate data for a site.

        Args:
            site (str): Site id_name (e.g. '_cont')
            model (str): Model name to filter by (e.g. 'historic', '_cesm2').
                         None returns all models.

        Returns:
            pd.DataFrame: columns time, model, precip, runoff, evapo, rechg
        """
        engine = self.get_engine()

        query  = """
            SELECT mm.time, mo.name AS model, mm.precip, mm.runoff, mm.evapo, mm.rechg
            FROM climate.monthly_mean mm
            JOIN climate.t_models mo  ON mm.id_model = mo.id_model
            JOIN sites.t_sites s      ON mm.id_site  = s.id_site
            WHERE s.id_name = :site
        """
        params = {'site': site if site.startswith('_') else '_' + site}

        if model is not None:
            query += ' AND mo.name = :model'
            params['model'] = model

        query += ' ORDER BY mo.name, mm.time'

        df = pd.read_sql(db.text(query), con=engine, params=params)
        engine.dispose()
        return df

    def get_daily_mean_climate(self, site, model=None):
        """Query daily mean climate data for a site.

        Args:
            site (str): Site id_name (e.g. '_cont')
            model (str): Model name to filter by (e.g. 'historic', '_cesm2').
                         None returns all models.

        Returns:
            pd.DataFrame: columns time, model, precip, runoff, evapo, rechg
        """
        engine = self.get_engine()

        query  = """
            SELECT dm.time, mo.name AS model, dm.precip, dm.runoff, dm.evapo, dm.rechg
            FROM climate.daily_mean dm
            JOIN climate.t_models mo  ON dm.id_model = mo.id_model
            JOIN sites.t_sites s      ON dm.id_site  = s.id_site
            WHERE s.id_name = :site
        """
        params = {'site': site if site.startswith('_') else '_' + site}

        if model is not None:
            query += ' AND mo.name = :model'
            params['model'] = model

        query += ' ORDER BY mo.name, dm.time'

        df = pd.read_sql(db.text(query), con=engine, params=params)
        engine.dispose()
        return df

    def get_yearly_mean_climate(self, site, model=None):
        """Query yearly mean climate data for a site.

        Args:
            site (str): Site id_name (e.g. '_cont')
            model (str): Model name to filter by (e.g. 'historic', '_cesm2').
                         None returns all models.

        Returns:
            pd.DataFrame: columns time, model, precip, runoff, evapo, rechg
        """
        engine = self.get_engine()

        query  = """
            SELECT ym.time, mo.name AS model, ym.precip, ym.runoff, ym.evapo, ym.rechg
            FROM climate.yearly_mean ym
            JOIN climate.t_models mo  ON ym.id_model = mo.id_model
            JOIN sites.t_sites s      ON ym.id_site  = s.id_site
            WHERE s.id_name = :site
        """
        params = {'site': site if site.startswith('_') else '_' + site}

        if model is not None:
            query += ' AND mo.name = :model'
            params['model'] = model

        query += ' ORDER BY mo.name, ym.time'

        df = pd.read_sql(db.text(query), con=engine, params=params)
        engine.dispose()
        return df

    def preview_cell_mask(self, site, file_path):
        """Plot the site boundary and NetCDF grid cells, coloured by in/out mask.

        Useful to verify that the spatial filter is correct before running a full import.

        Args:
            site (str): Site id_name (e.g. '_cont')
            file_path (str): Path to a help_example.out for that site
        """
        engine = self.get_engine()
        site_name = site if site.startswith('_') else '_' + site

        with engine.connect() as conn:
            row = conn.execute(db.text("""
                SELECT ST_AsText(geom) FROM sites.t_sites WHERE id_name = :id_name
            """), {'id_name': site_name}).fetchone()
        engine.dispose()

        if row is None or row[0] is None:
            print(f"No boundary found for '{site_name}'.")
            return

        boundary = shapely_wkt.loads(row[0])

        ds       = xr.open_datatree(file_path, engine='h5netcdf', phony_dims='sort')
        data     = ds['/data'].ds
        lats     = data['lat_dd'].values
        lons     = data['lon_dd'].values
        mask     = shapely.contains_xy(boundary, lons, lats)

        _, ax = plt.subplots(figsize=(8, 8))

        geoms = boundary.geoms if boundary.geom_type == 'MultiPolygon' else [boundary]
        for geom in geoms:
            plot_polygon(geom, ax=ax, facecolor='lightblue', edgecolor='steelblue', alpha=0.4, linewidth=0.8)

        ax.scatter(lons[~mask], lats[~mask], s=4, color='lightgrey', label=f'Outside ({(~mask).sum()})', zorder=2)
        ax.scatter(lons[mask],  lats[mask],  s=4, color='tomato',    label=f'Inside ({mask.sum()})',    zorder=3)

        ax.set_title(f'{site_name} — cell mask preview\n{mask.sum()}/{len(mask)} cells inside boundary')
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.legend()
        plt.tight_layout()
        plt.show()

    def get_available_params(self, site):
        """List available parameters for a site with their field ID and name.

        Args:
            site (str): Site id_name (e.g. '_cont')

        Returns:
            pd.DataFrame: columns field, mnemonique
        """
        engine = self.get_engine()
        site_name = site if site.startswith('_') else '_' + site

        df = pd.read_sql(db.text("""
            SELECT
                im.field,
                nom.mnemonique,
                im.collect_point_id,
                MIN(obs.timestamp) AS date_from,
                MAX(obs.timestamp) AS date_to
            FROM sites.t_imports im
            JOIN sites.t_collect_points cp            ON im.collect_point_id   = cp.id_collect_point
            JOIN sites.t_sites s                      ON cp.site_id            = s.id_site
            JOIN ref_nomenclature.t_nomenclatures nom ON im.field              = nom.id_nomenclature
            JOIN sites.daily_observations obs         ON obs.id_import         = im.id_import
            WHERE s.id_name = :site
            GROUP BY im.field, nom.mnemonique, im.collect_point_id
            ORDER BY im.field, im.collect_point_id
        """), con=engine, params={'site': site_name})
        engine.dispose()
        return df

    def get_collect_points(self, site):
        """List all collect points for a site with their IDs.

        Args:
            site (str): Site id_name (e.g. '_cont')

        Returns:
            pd.DataFrame: columns id_collect_point, name (or label)
        """
        engine = self.get_engine()
        site_name = site if site.startswith('_') else '_' + site
        df = pd.read_sql(db.text("""
            SELECT cp.id_collect_point, cp.label
            FROM sites.t_collect_points cp
            JOIN sites.t_sites s ON cp.site_id = s.id_site
            WHERE s.id_name = :site
            ORDER BY cp.id_collect_point
        """), con=engine, params={'site': site_name})
        engine.dispose()
        return df

    def export_observations(self, site, field, collect_point_id=None):
        """Export daily observed data for a site and field from sites.daily_observations.

        Args:
            site (str): Site id_name (e.g. '_cont')
            field (int): Nomenclature field ID (e.g. 12 for air_temperature)
            collect_point_id (int): Optional — filter to a specific collect point.
                                    If None, returns all collect points.

        Returns:
            pd.DataFrame: columns timestamp, daily_avg, id_import, collect_point_id, field
        """
        engine = self.get_engine()
        site_name = site if site.startswith('_') else '_' + site

        query = """
            SELECT obs.timestamp, obs.daily_avg, obs.id_import, obs.collect_point_id, obs.field
            FROM sites.daily_observations obs
            JOIN sites.t_collect_points cp ON obs.collect_point_id = cp.id_collect_point
            JOIN sites.t_sites s           ON cp.site_id           = s.id_site
            WHERE s.id_name = :site AND obs.field = :field
        """
        params = {'site': site_name, 'field': field}

        if collect_point_id is not None:
            query += ' AND obs.collect_point_id = :cp_id'
            params['cp_id'] = collect_point_id

        query += ' ORDER BY obs.collect_point_id, obs.timestamp'

        df = pd.read_sql(db.text(query), con=engine, params=params)
        engine.dispose()
        return df

    def export_reanalysis(self, site, field):
        """Export daily reanalysis data for a site and field from sites.daily_reanalysis.

        Args:
            site (str): Site id_name (e.g. '_cont')
            field (int): Nomenclature field ID

        Returns:
            pd.DataFrame: columns timestamp, daily_avg, site_id, field
        """
        engine = self.get_engine()
        site_name = site if site.startswith('_') else '_' + site

        df = pd.read_sql(db.text("""
            SELECT r.timestamp, r.daily_avg, r.site_id, r.field
            FROM sites.daily_reanalysis r
            JOIN sites.t_sites s ON r.site_id = s.id_site
            WHERE s.id_name = :site AND r.field = :field
            ORDER BY r.timestamp
        """), con=engine, params={'site': site_name, 'field': field})
        engine.dispose()
        return df
