"""
This module provides methods for interacting with the local database.
"""
import sqlite3
from typing import Type
import logging
from contextlib import closing
import datetime as dt
import re
import os
import pandas as pd
import numpy as np
from pandas.api.typing import NAType
import arcpy
from inatdatapipeline.client import (
    observations,
    annotations
)

sqlite3.register_adapter(dt.date, lambda d: d.isoformat())
sqlite3.register_adapter("date", lambda b: dt.date.fromisoformat(b.decode()))
sqlite3.register_adapter(NAType, lambda _: None)
sqlite3.register_adapter(np.int64, int)
sqlite3.register_adapter(np.int32, int)

logger = logging.getLogger("pipeline")

TABLE_WHITELIST = [
    "tracking_taxa",
    "inat_taxa",
    "tracking_rel",
    "users",
    "observations",
    "identifications",
    "annotations",
    "annotation_options",
    "annotation_values",
    "experts",
    "project_members",
    "mappings",
    "not_in_inat",
    "expert_identifications",
    "annotations_with_labels",
    "full_observations"
]

class DBManager:
    """
    This is an auto-closing class that can carry out specified operations on a local sqlite3 
    database.
    """
    def __init__(self, db_file: str):
        self._conn   : sqlite3.Connection = None
        self.db_file : str = db_file


    def __enter__(self):
        """
        Called when entering a "with" clause. Opens connection to database.
        """
        self.connect()
        return self


    def __exit__(self, exc_type, exc_value, traceback):
        """
        Called when exiting a "with" clause. Commits database transaction and closes connection.
        """
        self._conn.commit()
        if self._conn:
            self._conn.close()
            self._conn = None


    def __del__(self):
        if self._conn:
            self._conn.close()

    def connect(self):
        """
        Connect to sqlite database. Connection stored in self._conn. Closes previous connection 
        if one was open.
        """
        if self._conn:
            self._conn.close()

        if not os.path.exists(self.db_file):
            arcpy.management.CreateSQLiteDatabase(self.db_file, spatial_type="GEOPACKAGE")

        try:
            self._conn = sqlite3.connect(self.db_file)
        except sqlite3.Error as err:
            print("Error connecting to database:", err)
            raise


    def setup_db(self, sql_file_path: str):
        """
        Sets up the iNat database if by creating tables if they don't already exist. Automatically 
        commits transaction.
        """
        self.check_connection()

        try:
            # Read SQL schema file
            with open(sql_file_path, "r", encoding="utf-8") as fp:
                sql = fp.read()

            # Execute SQL instructions
            with closing(self._conn.cursor()) as cursor:
                cursor.executescript(sql)

        except sqlite3.Error as ex:
            raise sqlite3.Error("Error while creating tables.") from ex


    def check_connection(self):
        """Verify that the database connection is active. Raise sqlite3.Error if not."""
        if not self._conn:
            raise sqlite3.Error("Must be connected to a database")


    def insert_tracking(self, tracking_df: pd.DataFrame) -> int:
        """
        Inserts the tracking list into the database. Returns the number of rows inserted, or -1 
        if the dataframe is empty.

        Args: 
            tracking_df: A dataframe with the tracking list. Should conform to the 
            TrackingSchemaClean model, including the search_name and is_described columns.
        """
        self.check_connection()
        if tracking_df is None or len(tracking_df) == 0:
            return -1

        statements =  [
            """
                INSERT INTO tracking_taxa (
                    est_id, 
                    egt_id,
                    sci_name,
                    global_sci_name,
                    override_name,
                    classification_level,
                    is_described,
                    parent_egt_id,
                    element_type,
                    common_name,
                    family,
                    genus_egt_id,
                    author,
                    egt_uid,
                    srank,
                    track_status,
                    explorer,
                    elcode, 
                    growth_habit,
                    duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(est_id) 
                DO UPDATE SET
                    egt_id = excluded.egt_id,
                    sci_name = excluded.sci_name,
                    global_sci_name = excluded.global_sci_name,
                    override_name = excluded.override_name,
                    classification_level = excluded.classification_level,
                    is_described = excluded.is_described,
                    parent_egt_id = excluded.parent_egt_id,
                    element_type = excluded.element_type,
                    common_name = excluded.common_name,
                    family = excluded.family,
                    genus_egt_id = excluded.genus_egt_id,
                    author = excluded.author,
                    egt_uid = excluded.egt_uid,
                    srank = excluded.srank,
                    track_status = excluded.track_status,
                    explorer = excluded.explorer,
                    elcode = excluded.elcode,
                    growth_habit = excluded.growth_habit,
                    duration = excluded.duration
            """,
            """
                INSERT INTO parent_taxa (
                    parent_egt_id,
                    parent_sci_name
                )
                VALUES (?, ?)
                ON CONFLICT(parent_egt_id) 
                DO UPDATE SET
                    parent_sci_name = excluded.parent_sci_name
            """,
            """
                INSERT INTO genera (
                    genus_egt_id,
                    genus_sci_name
                )
                VALUES (?, ?)
                ON CONFLICT (genus_egt_id)
                DO UPDATE SET
                    genus_sci_name = excluded.genus_sci_name
            """
        ]

        tracking_cols = [
            "est_id",
            "egt_id",
            "sci_name", 
            "global_sci_name",
            "override_name",
            "classification_level",
            "is_described",
            "parent_egt_id",
            "element_type", 
            "common_name", 
            "family",
            "genus_egt_id",
            "author",
            "egt_uid",
            "srank",
            "track_status",
            "explorer",
            "elcode",
            "growth_habit",
            "duration"
        ]
        parent_cols = [
            "parent_egt_id",
            "parent_sci_name"
        ]
        genus_cols = [
            "genus_egt_id",
            "genus_sci_name",
        ]

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statements[0],
                list(tracking_df[tracking_cols].itertuples(index=False))
            )
            count = cursor.rowcount
            cursor.executemany(
                statements[1],
                list(tracking_df[parent_cols].dropna().itertuples(index=False))
            )
            cursor.executemany(
                statements[2],
                list(tracking_df[genus_cols].itertuples(index=False))
            )

        return count

    def insert_mappings(self, mapping_df: pd.DataFrame) -> int:
        """
        Inserts new taxon mappings into the database. Returns number of rows inserted, or -1 
        if the dataframe is empty.
        """
        if mapping_df is None or len(mapping_df) == 0:
            return -1

        statements = [
            """
            INSERT INTO inat_taxa (taxon_id, inat_name)
            VALUES (?, ?)
            ON CONFLICT(taxon_id) 
            DO UPDATE SET 
                inat_name = excluded.inat_name;
            """,
            """
            INSERT INTO tracking_rel (taxon_id, est_id, parent_egt_id, genus_egt_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(est_id) DO UPDATE SET taxon_id = excluded.taxon_id
            ON CONFLICT(parent_egt_id) DO UPDATE SET taxon_id = excluded.taxon_id
            ON CONFLICT(genus_egt_id) DO UPDATE SET taxon_id = excluded.taxon_id
            """
        ]

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statements[0],
                list(mapping_df[["taxon_id", "inat_name"]].itertuples(index=False))
            )
            cursor.executemany(
                statements[1],
                list(mapping_df[["taxon_id", "est_id", "parent_egt_id", "genus_egt_id"]].itertuples(index=False))
            )
            count = cursor.rowcount

        return count


    def _select_query(self, query: str) -> pd.DataFrame:
        """
        Helper function for doing a simple select query and putting the results in a dataframe. 
        Returns empty dataframe if there are no results.
        """
        with closing(self._conn.cursor()) as cursor:
            result = cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            df = pd.DataFrame(
                result.fetchall(),
                columns=columns
            )
        return df

    def check_table_exists(self, table: str) -> bool:
        """
        Helper function that checks if the given table/view exists in the database.
        """
        self.check_connection()
        with closing(self._conn.cursor()) as cursor:
            query = """
                SELECT name 
                FROM sqlite_master 
                WHERE type IN ('table', 'view') 
                    AND name = ?;
            """
            cursor.execute(query, (table,))
            exists = cursor.fetchone()

        return bool(exists)


    def select(self, table: str) -> pd.DataFrame:
        """
        Queries the given table and returns the results as a dataframe. Returns None if the table 
        doesn't exist. 

        Raises a ValueError if the provided table name is invalid. 
        Raises sqlite3.Error if an error occurs while querying the table.
        """
        self.check_connection()
        exists = self.check_table_exists(table)
        if not exists:
            raise ValueError(f"Table doesn't exist in database: \'{table}\'")

        # Check table string against list of valid tables
        if table not in TABLE_WHITELIST:
            raise ValueError(f"Invalid table name: \'{table}\'")

        try:
            return self._select_query("SELECT * FROM " + table)

        except sqlite3.Error as ex:
            raise sqlite3.Error(f"Error while querying table \'{table}\':") from ex


    def replace_project_members(self, member_ids: set[int]):
        """
        Replace project_members table with new entries
        """
        insert_statement =  """
            INSERT OR IGNORE INTO project_members (user_id)
            VALUES (?);
            """

        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                ids = [(id,) for id in member_ids]
                cursor.execute("DELETE FROM project_members")
                cursor.executemany(insert_statement, ids)
                count = cursor.rowcount
            return count

        except sqlite3.Error as ex:
            raise sqlite3.Error("Error while updating project members.") from ex


    def insert_users(self, users: list):
        """
        Inserts new users into users table
        """
        statement = """
        INSERT INTO users (user_id, login, name)
        VALUES (:user_id, :login, :name)
        ON CONFLICT (user_id)
        DO UPDATE SET 
            login = login,
            name = name;
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.executemany(statement, users)
                count = cursor.rowcount
            return count

        except sqlite3.Error as ex:
            raise sqlite3.Error("Error while inserting into users table.") from ex


    def insert_observations(self, obs_list: list[dict]) -> int:
        """
        Inserts new observations into observations table.
        """
        statement = """
        INSERT INTO observations (
            observation_id,
            uuid,
            observer_id,
            taxon_id,
            license,
            latitude,
            longitude,
            latitude_private,
            longitude_private,
            coordinate_precision,
            coordinate_precision_public,
            observed_on,
            observed_on_string,
            created_at,
            updated_at,
            quality_grade,
            url,
            description,
            id_agreements,
            id_disagreements,
            place_guess,
            place_guess_private,
            captive_cultivated,
            obscured,
            has_photo,
            has_recording
        )
        VALUES (
            :observation_id,
            :uuid,
            :observer_id,
            :taxon_id,
            :license,
            :latitude,
            :longitude,
            :latitude_private,
            :longitude_private,
            :coordinate_precision,
            :coordinate_precision_public,
            :observed_on,
            :observed_on_string,
            :created_at,
            :updated_at,
            :quality_grade,
            :url,
            :description,
            :id_agreements,
            :id_disagreements,
            :place_guess,
            :place_guess_private,
            :captive_cultivated,
            :obscured,
            :has_photo,
            :has_recording
        )
        ON CONFLICT (observation_id)
        DO UPDATE SET
            observer_id = excluded.observer_id,
            uuid = excluded.uuid,
            taxon_id = excluded.taxon_id,
            license = excluded.license,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            latitude_private = excluded.latitude_private,
            longitude_private = excluded.longitude_private,
            coordinate_precision = excluded.coordinate_precision,
            coordinate_precision_public = excluded.coordinate_precision_public,
            observed_on = excluded.observed_on,
            observed_on_string = excluded.observed_on_string,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            quality_grade = excluded.quality_grade,
            url = excluded.url,
            description = excluded.description,
            id_agreements = excluded.id_agreements,
            id_disagreements = excluded.id_disagreements,
            place_guess = excluded.place_guess,
            place_guess_private = excluded.place_guess_private,
            captive_cultivated = excluded.captive_cultivated,
            obscured = excluded.obscured,
            has_photo = excluded.has_photo,
            has_recording = excluded.has_recording
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.executemany(statement, obs_list)
                count = cursor.rowcount
        except sqlite3.Error as err:
            raise sqlite3.Error("Error while inserting into observations table.") from err

        return count


    def insert_identifications(self, identifications: list[dict]) -> int:
        """Insert identifications into the identifications table."""
        if identifications is None or len(identifications) == 0:
            return 0
        statement = """
        INSERT INTO identifications (
            identification_id,
            observation_id,
            user_id,
            taxon_id,
            created_at
        )
        VALUES ( 
            :identification_id,
            :observation_id,
            :user_id,
            :taxon_id,
            :created_at
        )
        ON CONFLICT (identification_id)
        DO UPDATE SET
            identification_id = excluded.identification_id,
            observation_id = excluded.observation_id,
            user_id = excluded.user_id,
            taxon_id = excluded.taxon_id,
            created_at = excluded.created_at
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.executemany(statement, identifications)
                count = cursor.rowcount
        except sqlite3.Error as err:
            raise sqlite3.Error("Error while inserting into identifications table.") from err

        return count


    def insert_annotations(self, ann_list: list[dict]) -> int:
        """Insert annotations into the annotations table."""
        if ann_list is None or len(ann_list) == 0:
            return 0

        statement = """
        INSERT INTO annotations (
            observation_id,
            annotation_id,
            value_id,
            user_id,
            vote_score
        )
        VALUES (
            :observation_id,
            :annotation_id,
            :value_id,
            :user_id,
            :vote_score
        )
        ON CONFLICT (observation_id, annotation_id, value_id)
        DO UPDATE SET
            user_id = excluded.user_id,
            vote_score = excluded.vote_score
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.executemany(statement, ann_list)
                count = cursor.rowcount
        except sqlite3.Error as err:
            raise sqlite3.Error("Error while inserting into annotations table.") from err

        return count


    def update_checked_date(self, complete_taxa: set):
        """
        Update the last checked date for taxa whose downloads were completed.
        """
        if len(complete_taxa) == 0:
            return

        placeholders = ', '.join(['?'] * len(complete_taxa))
        statement = f"""
        UPDATE inat_taxa
        SET date_updated = ?
        WHERE taxon_id IN ({placeholders})
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.execute(statement, [dt.date.today()] + list(complete_taxa))
        except sqlite3.Error as err:
            raise sqlite3.Error("Error while updating taxon last checked dates.") from err


    def get_expert_identifications(self):
        """
        Get identifications made by experts whose expertise matches the taxon.
        """
        self.check_connection()
        try:
            self._conn.create_function("REGEXP_MATCH", 2, DBManager.match_wildcards)

        except sqlite3.Error as ex:
            msg = "Error while creating expert identification filter statement."
            raise sqlite3.Error(msg) from ex

        query = """
            SELECT * FROM expert_identifications
            WHERE REGEXP_MATCH(elcode, expertise) = 1;
            """
        try:
            df = self._select_query(query)
        except sqlite3.Error as ex:
            raise sqlite3.Error("Error while querying expert identifications.") from ex

        return df


    def update_experts(self, df: pd.DataFrame):
        """
        Update the experts table using the given dataframe.

        Raises sqlite3.Error if the columns aren't the expected names or if another database 
        exception occurs.
        """
        self.check_connection()
        statement = "INSERT INTO experts (user_id, expertise) VALUES (:user_id, :expertise);"

        tuples = df.to_dict(orient="records")

        with closing(self._conn.cursor()) as cursor:
            cursor.execute("DELETE FROM experts")
            cursor.executemany(statement, tuples)
            count = cursor.rowcount

        return count


    @staticmethod
    def match_wildcards(elcode, pattern_string):
        """
        Converts SQL wildcards (A%|I%) into a corresponding regex pattern and checks if the elcode 
        matches.
        """
        try:
            if not elcode or not pattern_string:
                return 0

            elcode_str = str(elcode).strip()
            pattern_str = str(pattern_string).strip()

            if not elcode_str or not pattern_str:
                return 0

            patterns = pattern_string.split('|')
            regex_parts = []

            for p in patterns:
                safe_p = p.replace(r"%", ".*")
                regex_parts.append(safe_p)

            combined_regex = "^(%s)$" % "|".join(regex_parts)
            return 1 if re.match(combined_regex, elcode) else 0

        except:
            print("\n ---  Crash detected ---")
            print(f"Inputs causing crash: elcode={repr(elcode)}, pattern={repr(pattern_string)}")
            print("--------------------------")
            raise


    def update_annotations(self, ann: annotations.AnnotationOptions) -> int:
        """
        Makes sure all three annotations tables are set up, then inserts the annotations and
        annotation values into the database.
        """
        self.check_connection()

        statements = [
            """
            INSERT OR IGNORE INTO annotation_options (annotation_id, label)
            VALUES (:annotation_id, :label)
            """,
            """
            INSERT OR IGNORE INTO annotation_values (value_id, annotation_id, label)
            VALUES (:value_id, :annotation_id, :label)
            """
        ]
        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(statements[0], ann.categories)
            cursor.executemany(statements[1], ann.values)
            count = cursor.rowcount

        return count


    def insert_observation_results(self, results: observations.ObservationResults):
        """
        Helper function that inserts all observations from API request into the database.

        Takes care of opening the database connection.
        """
        if len(results.observations) == 0:
            raise ValueError("No observations to insert.")
        with self as db:
            obs_count = db.insert_observations(results.observations)
            user_count = (
                db.insert_users(results.users)
                if len(results.users) > 0 else 0
            )
            ident_count = (
                db.insert_identifications(results.identifications)
                if len(results.identifications) >  0 else 0
            )
            annotation_count = (
                db.insert_annotations(results.annotations)
                if len(results.annotations) > 0 else 0
            )
            db.update_checked_date(results.completed_taxa)

        # Report results
        logger.info("Inserted new records into database:")
        logger.info("Users:            %i", user_count)
        logger.info("Observations:     %i", obs_count)
        logger.info("Identifications:  %i", ident_count)
        logger.info("Annotations:      %i", annotation_count)

    @staticmethod
    def extract_val(result: tuple, val_type: Type):
        """Helper function that extracts a value from a single-value query result"""
        if not result:
            if val_type is int:
                return 0
            return None

        try:
            result_str = result[0]
            result_val = val_type(result_str)
        except (ValueError, KeyError) as ex:
            raise ValueError(
                f"Statistic in database is in an unexpected format: {result_str}"
            ) from ex

        return result_val


    def get_request_count(self, today: dt.date) -> int:
        """
        Fetches today's request count from the stats table. If the current request count date is
        different from the 'today' parameter, returns 0.
        """
        self.check_connection()
        today_str = today.strftime("%d/%m/%Y")

        with closing(self._conn.cursor()) as cursor:
            # Get current request count
            cursor.execute("SELECT stat_value FROM stats WHERE stat_key = 'request_count'")
            count = self.extract_val(cursor.fetchone(), int)

            # Get current request count date
            cursor.execute("SELECT stat_value FROM stats WHERE stat_key = 'request_count_date'")
            date_str = self.extract_val(cursor.fetchone(), str)
            
        if not date_str or today_str == date_str:
            return count
        return 0


    def update_request_count(self, count: int, date: dt.date):
        """
        Updates today's request count in the stats table.
        """
        self.check_connection()

        replace_count_sql =  """
            INSERT OR REPLACE INTO stats (stat_key, stat_value)
            VALUES ('request_count', ?)
        """
        replace_date_sql = """
            INSERT OR REPLACE INTO stats (stat_key, stat_value)
            VALUES ('request_count_date', ?)
        """
        date_str = date.strftime("%d/%m/%Y")
        with closing(self._conn.cursor()) as cursor:
            cursor.execute(replace_count_sql, (str(count),))
            cursor.execute(replace_date_sql, (date_str,))
