"""
This module provides methods for interacting with the local database.
"""
import sqlite3
import logging
from contextlib import closing
import datetime as dt
import re
import pandas as pd
from inatdatapipeline.client import (
    observations,
    annotations
)

sqlite3.register_adapter(dt.date, lambda d: d.isoformat())
sqlite3.register_adapter("date", lambda b: dt.date.fromisoformat(b.decode()))

logger = logging.getLogger("pipeline")

create_statements = {
    "tracking_taxa":
        """
        CREATE TABLE IF NOT EXISTS tracking_taxa (
            est_id                int     NOT NULL PRIMARY KEY,
            sci_name              text,
            search_name           text,
            is_described          boolean CHECK (is_described IN (NULL, true, false)),
            element_type          text,
            scientific_name       text,
            common_name           text,
            element_name          text,
            family                text,
            author                text,
            egt_uid               int     NOT NULL,
            srank                 text,
            track_status          text,
            explorer              text,
            explorer_link         text,
            elcode                text    NOT NULL,
            growth_habit          text,
            duration              text
        );
        """,

    "inat_taxa":        
        """
        CREATE TABLE IF NOT EXISTS inat_taxa (
            taxon_id              int     PRIMARY KEY NOT NULL,
            inat_name             text,
            date_updated          text
        );
        """,

    "tracking_rel":
        """
        CREATE TABLE IF NOT EXISTS tracking_rel (
            taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
            est_id                int     NOT NULL REFERENCES tracking_taxa(est_id),
            PRIMARY KEY(taxon_id, est_id)
        );
        """,

    "tracking_trigger": 
        """
        CREATE TRIGGER IF NOT EXISTS fk_cascade_delete_tracking
        AFTER DELETE ON inat_taxa
        BEGIN
            DELETE FROM tracking_rel WHERE taxon_id = OLD.taxon_id;
        END;
        """,

    "inat_taxa_alternatives":
        """
        CREATE TABLE IF NOT EXISTS inat_taxa_alternatives (
            taxon_id                int     NOT NULL REFERENCES inat_taxa(taxon_id),
            alternative_taxon_id    int     NOT NULL,
            alternative_inat_name   str
        )
        """,

    "users":
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id               int     PRIMARY KEY NOT NULL,
            login                 text,
            name                  text
        );
        """,

    "observations":
        """
        CREATE TABLE IF NOT EXISTS observations (
            observation_id              int     PRIMARY KEY NOT NULL,
            uuid                        text    NOT NULL,
            observer_id                 int     NOT NULL REFERENCES users(user_id),
            taxon_id                    int     NOT NULL REFERENCES inat_taxa(taxon_id),
            license                     text,
            latitude                    float,
            longitude                   float,
            latitude_private            float,
            longitude_private           float,
            coordinate_precision        float,
            coordinate_precision_public float,
            observed_on                 text,
            observed_on_string          text,
            created_at                  text,
            updated_at                  text,
            quality_grade               text,
            url                         text,
            description                 text,
            id_agreements               int,
            id_disagreements            int,
            place_guess                 text,
            place_guess_private         text,
            captive_cultivated          boolean CHECK (captive_cultivated IN (NULL, true, false)),
            obscured                    boolean CHECK (obscured IN (NULL, true, false)),
            has_photo                   boolean CHECK (has_photo IN (NULL, true, false)),
            has_recording               boolean CHECK (has_recording IN (NULL, true, false))
        );
        """,

    "experts":
        """
        CREATE TABLE IF NOT EXISTS experts (
            user_id               int     PRIMARY KEY,
            expertise             text
        );
        """,

    "identifications":
        """
        CREATE TABLE IF NOT EXISTS identifications (
            identification_id     int     PRIMARY KEY NOT NULL,
            observation_id        int     NOT NULL REFERENCES observations(observation_id),
            user_id               int     NOT NULL REFERENCES users(user_id),
            taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
            created_at            text
        );
        """,

    "mappings":
        """
        CREATE VIEW IF NOT EXISTS mappings (
            est_id, 
            elcode, 
            sci_name, 
            search_name,
            is_described,
            common_name, 
            taxon_id, 
            inat_name, 
            date_updated
        ) AS SELECT 
            tt.est_id, 
            tt.elcode, 
            tt.sci_name, 
            tt.search_name,
            tt.is_described,
            tt.common_name, 
            it.taxon_id, 
            it.inat_name, 
            it.date_updated
        FROM tracking_taxa AS tt
        JOIN tracking_rel AS tr ON tt.est_id = tr.est_id
        JOIN inat_taxa AS it ON tr.taxon_id = it.taxon_id;
        """,

    "project_members":
        """
        CREATE TABLE IF NOT EXISTS project_members (
            user_id int PRIMARY KEY NOT NULL
        );
        """,

    "not_in_inat":
        """
        CREATE VIEW IF NOT EXISTS not_in_inat 
        AS SELECT * 
        FROM tracking_taxa AS tt
        LEFT JOIN tracking_rel AS tr
        ON tt.est_id = tr.est_id
        WHERE tr.est_id IS NULL;
        """,

    "expert_identifications":
        """
        CREATE VIEW IF NOT EXISTS expert_identifications (
            identification_id,
            observation_id,
            user_id,
            login,
            name,
            taxon_id,
            created_at,
            est_id,
            elcode,
            expertise
        )
        AS SELECT
            id.identification_id,
            id.observation_id,
            id.user_id,
            us.login,
            us.name,
            id.taxon_id,
            id.created_at,
            tr.est_id,
            tr.elcode,
            ex.expertise
        FROM identifications AS id
        LEFT JOIN tracking_rel 
            ON id.taxon_id = tracking_rel.taxon_id
        LEFT JOIN tracking_taxa AS tr 
            ON tracking_rel.est_id = tr.est_id
        JOIN experts AS ex 
            ON id.user_id = ex.user_id
        JOIN users AS us
            ON id.user_id = us.user_id;
        """,

    "annotation_options":
        """
        CREATE TABLE IF NOT EXISTS annotation_options (
            annotation_id       int     PRIMARY KEY NOT NULL,
            label               text    NOT NULL
        )
        """,

    "annotation_values":
        """
        CREATE TABLE IF NOT EXISTS annotation_values (
            annotation_id       int     NOT NULL REFERENCES annotations(annotation_id),
            value_id            int     NOT NULL,
            label               text    NOT NULL,
            PRIMARY KEY(value_id, annotation_id)
        )
        """,

    "annotations":
        """
        CREATE TABLE IF NOT EXISTS annotations (
            annotation_id       int     NOT NULL,
            value_id            int     NOT NULL,
            observation_id      int     NOT NULL,
            user_id             int     NOT NULL,
            vote_score          int     NOT NULL,
            PRIMARY KEY(annotation_id, value_id, observation_id),
            FOREIGN KEY(annotation_id, value_id) 
                REFERENCES annotation_values(annotation_id, value_id)
        )
        """,

    "annotations_with_labels":
        """
        CREATE VIEW IF NOT EXISTS annotations_with_labels (
            observation_id,
            annotation_id,
            value_id,
            annotation_label,
            value_label,
            user_id,
            vote_score
        )
        AS SELECT
            ann.observation_id,
            ann.annotation_id,
            ann.value_id,
            ao.label,
            av.label,
            ann.user_id,
            ann.vote_score
        FROM annotations ann
        JOIN annotation_values av
            ON ann.value_id = av.value_id
        JOIN annotation_options ao
            ON ann.annotation_id = ao.annotation_id
        """,

    "full_observations":
        """
        CREATE VIEW IF NOT EXISTS full_observations
        AS SELECT
            obs.observation_id,
            obs.uuid,
            obs.observer_id,
            us.name,
            us.login,
            obs.taxon_id,
            obs.license,
            obs.latitude,
            obs.longitude,
            obs.latitude_private,
            obs.longitude_private,
            obs.coordinate_precision,
            obs.coordinate_precision_public,
            obs.observed_on,
            obs.observed_on_string,
            obs.created_at,
            obs.updated_at,
            obs.quality_grade,
            obs.url,
            obs.description,
            obs.id_agreements,
            obs.id_disagreements,
            obs.place_guess,
            obs.place_guess_private,
            obs.captive_cultivated,
            obs.obscured,
            obs.has_photo,
            obs.has_recording,
            tt.est_id,
            tt.element_type,
            tt.sci_name,
            tt.search_name,
            tt.is_described,
            tt.scientific_name,
            tt.common_name,
            tt.element_name,
            tt.family,
            tt.author,
            tt.egt_uid,
            tt.srank,
            tt.track_status,
            tt.explorer,
            tt.explorer_link,
            tt.elcode,
            tt.growth_habit,
            tt.duration
        FROM observations obs
        JOIN users us
            ON obs.observer_id = us.user_id
        LEFT JOIN tracking_rel tr1
            ON obs.taxon_id = tr1.taxon_id
        LEFT JOIN inat_taxa_alternatives ita
            ON obs.taxon_id = ita.alternative_taxon_id AND tr1.taxon_id IS NULL
        LEFT JOIN tracking_rel tr2
            ON ita.taxon_id = tr2.taxon_id AND ita.taxon_id IS NOT NULL
        JOIN tracking_taxa tt
            ON tt.est_id = COALESCE(tr1.est_id, tr2.est_id);
        """
}


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

        try:
            self._conn = sqlite3.connect(self.db_file)
        except sqlite3.Error as err:
            print("Error connecting to database:", err)
            raise


    def setup_db(self):
        """
        Sets up the iNat database if by creating tables if they don't already exist. Automatically 
        commits transaction.
        """
        self.check_connection()

        try:
            with closing(self._conn.cursor()) as cursor:
                for _, statement in create_statements.items():
                    cursor.execute(statement)
        except sqlite3.Error as ex:
            raise sqlite3.Error(f"Error while creating tables: {ex}")


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
        if tracking_df is None or len(tracking_df) == 0:
            return -1

        statement =  """
            INSERT INTO tracking_taxa (
                sci_name,
                search_name,
                is_described,
                est_id, 
                element_type,
                scientific_name, 
                common_name,
                element_name,
                family,
                author,
                egt_uid,
                srank,
                track_status,
                explorer,
                explorer_link,
                elcode, 
                growth_habit,
                duration
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(est_id) 
            DO UPDATE SET
                sci_name = excluded.sci_name, 
                search_name = excluded.search_name,
                is_described = excluded.is_described,
                element_type = excluded.element_type,
                scientific_name = excluded.scientific_name,
                common_name = excluded.common_name,
                element_name = excluded.element_name,
                family = excluded.family,
                author = excluded.author,
                egt_uid = excluded.egt_uid,
                srank = excluded.srank,
                track_status = excluded.track_status,
                explorer = excluded.explorer,
                explorer_link = excluded.explorer_link,
                elcode = excluded.elcode,
                growth_habit = excluded.growth_habit,
                duration = excluded.duration
            """

        tracking_cols = [
            "sci_name", 
            "search_name",
            "is_described",
            "est_id",
            "element_type", 
            "scientific_name", 
            "common_name", 
            "element_name",
            "family",
            "author",
            "egt_uid",
            "srank",
            "track_status",
            "explorer",
            "explorer_link",
            "elcode",
            "growth_habit",
            "duration"
        ]

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statement,
                list(tracking_df[tracking_cols].itertuples(index=False))
            )
            count = cursor.rowcount

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
            INSERT OR IGNORE INTO inat_taxa (taxon_id, inat_name)
            VALUES (?, ?)
            ON CONFLICT(taxon_id) 
            DO UPDATE SET 
                inat_name = excluded.inat_name;
            """,
            """
            INSERT OR IGNORE INTO tracking_rel (taxon_id, est_id)
            VALUES (?, ?);
            """
        ]

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statements[0],
                list(mapping_df[["taxon_id", "inat_name"]].itertuples(index=False))
            )
            cursor.executemany(
                statements[1],
                list(mapping_df[["taxon_id", "est_id"]].itertuples(index=False))
            )
            count = cursor.rowcount

        return count


    def insert_alternatives(self, alternatives_df: pd.DataFrame) -> int:
        """
        Inserts name alternatives into the inat_taxa_alternatives table. Returns number of rows
        inserted, or 0 if the dataframe is empty.
        """
        if alternatives_df is None or len(alternatives_df) == 0:
            return 0

        statement = """
            INSERT OR IGNORE INTO inat_taxa_alternatives (
                taxon_id,
                alternative_taxon_id,
                alternative_inat_name
            )
            VALUES (?, ?, ?)
            """

        try:
            with closing(self._conn.cursor()) as cursor:
                cursor.executemany(statement, list(alternatives_df.itertuples(index=False)))
                count = cursor.rowcount
            return count

        except sqlite3.Error as ex:
            raise sqlite3.Error(f"Error while inserting taxon name alternatives: {ex}")


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
        if create_statements.get(table) is None:
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
                cursor.execute("DROP TABLE IF EXISTS project_members;")
                cursor.execute(create_statements["project_members"])
                cursor.executemany(insert_statement, ids)
                count = cursor.rowcount
            return count

        except sqlite3.Error as ex:
            raise sqlite3.Error(f"Error while updating project members: {ex}")


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
            raise sqlite3.Error(f"Error while inserting into users table: {ex}")


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
            raise sqlite3.Error(f"Error while inserting into observations table: {err}")

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
            raise sqlite3.Error(f"Error while inserting into identifications table: {err}")

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
            raise sqlite3.Error(f"Error while inserting into annotations table: {err}")

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
            msg = f"Error while updating taxon last checked dates: {err}"
            raise sqlite3.Error(msg)


    def get_expert_identifications(self):
        """
        Get identifications made by experts whose expertise matches the taxon.
        """
        self.check_connection()
        try:
            self._conn.create_function("REGEXP_MATCH", 2, DBManager.match_wildcards)
            self._conn.execute(create_statements["expert_identifications"])
        except sqlite3.Error as ex:
            msg = f"Error while creating expert identification filter statement: {ex}"
            raise sqlite3.Error(msg)

        query = """
        SELECT * FROM expert_identifications
        WHERE REGEXP_MATCH(elcode, expertise) = 1;
        """
        try:
            df = self._select_query(query)
        except sqlite3.Error as ex:
            msg = f"Error while querying expert identifications: {ex}"
            raise sqlite3.Error(msg)

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
            cursor.execute("DROP TABLE IF EXISTS experts")
            cursor.execute(create_statements["experts"])
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

            combined_regex = f"^({"|".join(regex_parts)})$"
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
        # Set up tables
        self._conn.execute(create_statements["annotation_options"])
        self._conn.execute(create_statements["annotation_values"])
        self._conn.execute(create_statements["annotations_with_labels"])

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
                if len(results.annotations) > 0 else 0
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
