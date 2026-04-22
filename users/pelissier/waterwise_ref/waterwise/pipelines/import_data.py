import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema
import sqlalchemy as db
import os

class DatabaseTool:
    
    def __init__(self, testmode= False):
        self.__host = 'ns324.evxonline.net'
        self.__user = 'postgres'
        self.__password = '8jC56guc8KVKv3t9vW3R'
        self.__port = '5432'
        if testmode:
            self.database = 'waterwise-db'
        else:
            self.database = 'test_db'
            
    def get_host(self):
        return self.__host
    
    def get_user(self):
        return self.__user
    
    def get_engine(self):
        return create_engine(f'postgresql+psycopg2://{self.__user}:{self.__password}@{self.__host}:{self.__port}/{self.database}')

    
    
    # Schema and Table management
    def create_schema(self, name):
        """Verify if the schema exists already and if not create a new schema

        Args:
            name (str): schema name
        """
        # Connexion via SQLAlchemy
        engine = self.get_engine()


        # Control if exits return directly
        inspector = db.inspect(engine)
        if name in inspector.get_schema_names():
            return
        
        with engine.connect() as conn:
            conn.execute(CreateSchema(name, if_not_exists=True))
            conn.commit()

        # Control 
        inspector = db.inspect(engine)
        if name in inspector.get_schema_names():
            print(f"Schema {name} created!")
                
        engine.dispose()
        return 


    def create_table_prediction_csv(self, schema, name):
        """Function creating a table formatted for prediction csv (time, precip, runoff, evapo and rechg).

        Args:
            schema (str): Schema name
            name (str): Table name
        """
        table_name = 't_' + name

        # Connexion via SQLAlchemy
        engine = self.get_engine()
        
        # Control 
        inspector = db.inspect(engine)
        if table_name in inspector.get_table_names(schema=schema):
            print(f"Table {table_name} exists already in schema {schema}!")
            return

        # Table creation
        metadata = db.MetaData(schema=schema) 
        model = db.Table(table_name, metadata,
                            db.Column('time', db.TIMESTAMP(), nullable= False),
                            db.Column('precip', db.Float()),
                            db.Column('runoff', db.Float()),
                            db.Column('evapo', db.Float()),
                            db.Column('rechg', db.Float())
                            ) 
        metadata.create_all(engine)
        
        inspector = db.inspect(engine)
        #print(inspector.get_table_names(schema=schema))
        with engine.connect() as conn:
            conn.execute(db.text(f"SELECT create_hypertable('{schema + '.' + table_name}', 'time');"))
            conn.commit()

        if table_name in inspector.get_table_names(schema=schema):
            print(f"Table {table_name} created in schema {schema}!")
        
        engine.dispose()
        return 
    
    
    def create_table_input_csv(self, name, schema='cerra'):
        """Function creating a table formatted for input csv.\n
        File structure:\n
        --------------------------------
        lat     | cell latitude\n
        --------------------------------
        lon     | cell longitude\n
        --------------------------------
        date    | values for each cell
        --------------------------------

        Args:
            name (str): Table name
            schema (str, optional): Schema name. Defaults to 'cerra'.
        """
        table_name = 't' + name

        # Connexion via SQLAlchemy
        engine =self.get_engine()
        
        # Control 
        inspector = db.inspect(engine)
        if table_name in inspector.get_table_names(schema=schema):
            print(f"Table {table_name} exists already in schema {schema}!")
            return

        # Table creation
        metadata = db.MetaData(schema=schema) 
        model = db.Table(table_name, metadata,
                            db.Column('time', db.TIMESTAMP(), nullable= False),
                            db.Column('lat', db.Float(), nullable= False),
                            db.Column('lon', db.Float(), nullable= False),
                            db.Column('air_temp', db.Float()),
                            db.Column('precip', db.Float())
                            ) 
        metadata.create_all(engine)
        
        inspector = db.inspect(engine)
        #print(inspector.get_table_names(schema=schema))
        with engine.connect() as conn:
            conn.execute(db.text(f"SELECT create_hypertable('{schema + '.' + table_name}', 'time');"))
            conn.commit()

        if table_name in inspector.get_table_names(schema=schema):
            print(f"Table {table_name} created in schema {schema}!")
        
        engine.dispose()
        return 


    def delete_table(self, schema, table):
        """Delete a table with a specific schema and name.

        Args:
            schema (str): Schema name
            table (str): Table name like "t_cont"
        """

        # Connexion via SQLAlchemy
        engine = self.get_engine()

        with engine.connect() as conn:
            conn.execute(db.text(f"DROP TABLE IF EXISTS {schema}.{table};"))
            conn.commit()
        
        # Control 
        inspector = db.inspect(engine)
        if table not in inspector.get_table_names(schema=schema):
            print(f"Droped table: {table}!")
        
        engine.dispose()
        return
        
    
    # Upload data 
    def import_prediction_csv(self, path):
        """Upload to the database the outputs from file "help_example_daily_mean.csv".

        Args:
            path (str): Path to file.
        """

        # Connexion via SQLAlchemy
        engine = self.get_engine()

        sites = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]

        for site in sites:
            path_site = os.path.join(path, site)

            models = [d for d in os.listdir(path_site) if os.path.isdir(os.path.join(path_site, d))]

            #print(site, models)
            for model in models:
                # Create schema
                self.create_schema(model.lower()[1:])

                # Create table
                self.create_table_prediction_csv(schema=model.lower()[1:], name=site.lower())

                # Find csv file
                filename = 'help_example_daily_mean.csv'
                path_file = os.path.join(path_site, model, filename)

                try:
                    data = pd.read_csv(path_file)
                except OSError as e:
                    print('Error:', e)

                # Change column names
                data.columns = ['time', 'precip', 'runoff', 'evapo', 'rechg']
                #print(data.head())


                # Insert to database
                data.to_sql(
                    't_' + site.lower(), 
                    schema=model.lower()[1:], 
                    con=engine, 
                    if_exists='replace',  # ou 'replace' si tu veux recréer la table
                    index=False
                )
            print(f"Site {site} done!")


        engine.dispose()
        return
    
    
    """ def import_cerra_csv(self, path):
        
        sites = [d for d in os.listdir(path) if d[0] == '_']
        
        air_temp = 'airtemp_input_data.csv'
        precip = 'precip_input_data.csv'

        for site in sites:
            
            # Open files
            #TODO Control path coherence
            df_air_temp = pd.read_csv(os.path.join(path, site, 'results_pyhelp', air_temp), header=None)
            df_precip = pd.read_csv(os.path.join(path, site, 'results_pyhelp', precip), header=None)

            # Test if coords of the cells are the same in both files
            if not df_air_temp.iloc[0:2, 1:].equals(df_precip.iloc[0:2, 1:]):
                print(f"Error: cells in {air_temp} and {precip} are not the same for site {site}. They need to be the same to import into the database.")
            
            # Test if dates are the same in both files
            if not df_air_temp.iloc[2:, 0].equals(df_precip.iloc[2:, 0]):
                print(f"Error: dates in {air_temp} and {precip} are not the same for site {site}. They need to be the same to import into the database.")

            # Extract lat and lon of both to make sure that the cells are the same
            latitudes = df_air_temp.iloc[0, 1:].dropna().astype(float).tolist()
            longitudes = df_air_temp.iloc[1, 1:].dropna().astype(float).tolist()

            # Extract time series
            df_data_air = df_air_temp.iloc[2:].reset_index(drop=True)
            df_data_precip = df_precip.iloc[2:].reset_index(drop=True) # Don't need the date column (same as air_temp)

            # Put everything together again 
            rows = []
            for i in range(len(df_data_air)):
                date = pd.to_datetime(df_data_air[0][i], dayfirst=True)

                for j, (lat, lon) in enumerate(zip(latitudes, longitudes)):
                    rows.append({
                        'time':      date,
                        'lat':  lat,
                        'lon': lon,
                        'air_temp': float(df_data_air[j + 1][i]),
                        'precip': float(df_data_precip[j + 1][i])
                    })

            df_final = pd.DataFrame(rows)
            print(df_final.head())

        return df_final """
    
    
    # Export
    def export_data(self, site, param):
        
        params = {'air_temperature': 12, 'total_precipitation': 18, 'solar_radiation': 28, 'river_discharge': 2}
    
        if param not in params.keys():
            return print(f"Wrong parameter, choose from these: {[p for p in params.keys()]}")
        
        
        engine = self.get_engine()
                
        df = pd.read_sql(db.text(f"SELECT obs.timestamp as time, obs.value "\
                                f"FROM sites.t_imports im "\
                                f"JOIN  sites.t_observations obs "\
                                f"ON im.id_import = obs.id_import "\
                                f"JOIN sites.t_collect_points cp "\
                                f"ON im.collect_point_id = cp.id_collect_point "\
                                f"JOIN sites.t_sites s "\
                                f"ON cp.site_id = s.id_site "\
                                f"WHERE s.id_name = '{site}' AND im.type = 'Observation' AND im.field = {params[param]}"), 
                                con=engine)
        
        engine.dispose()
        return df
    
    def available_data(self, site):

        engine = self.get_engine()
                
        df = pd.read_sql(db.text(f"SELECT nom.mnemonique "\
                                f"FROM ref_nomenclature.t_nomenclatures nom "\
                                f"JOIN sites.t_imports im "\
                                f"ON nom.id_nomenclature = im.field "\
                                f"JOIN sites.t_collect_points cp "\
                                f"ON im.collect_point_id = cp.id_collect_point "\
                                f"JOIN sites.t_sites s "\
                                f"ON cp.site_id = s.id_site "\
                                f"WHERE s.id_name = '{site}' AND im.type = 'Observation'"), 
                                con=engine).drop_duplicates()
        
        engine.dispose()
        return df