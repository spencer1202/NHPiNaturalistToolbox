"""
observations.py

This module is responsible for downloading iNaturalist observations and structuring them into the
database schema. 
"""
#### Standard imports ####
import datetime as dt
import os
import logging
import json
from typing import Optional, Self
from dataclasses import dataclass, field

#### Third-party imports ####
import pandas as pd
from pandera.errors import SchemaError
from pandera.typing import DataFrame
import prison

#### Local imports ####
from inatdatapipeline.client import helpers
from inatdatapipeline import config
from inatdatapipeline.schemas import (
    INatTaxaSchema,
    ObservationSchema,
    IdentificationsSchema,
    UsersSchema,
    AnnotationsSchema,
    DATE_FORMAT
)

from inatdatapipeline.client.authentication import INaturalistAuth

#### Setup ####
logger = logging.getLogger('pipeline')

# Location of file with observation fields to search for
FIELDS_FILE = "obs_fields.json"
FIELDS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), FIELDS_FILE)


@dataclass
class ObservationResultsRaw:
    """
    Structures results of the iNaturalist observation requests.
    """
    observations    : list[dict]    = field(default_factory=list)
    identifications : list[dict]    = field(default_factory=list)
    users           : list[dict]    = field(default_factory=list)
    annotations     : list[dict]    = field(default_factory=list)
    completed_taxa  : set           = field(default_factory=set)


@dataclass
class ObservationUnpacker(ObservationResultsRaw):
    """
    Adds a working list of users and observation IDs, with methods to assist unpacking API results
    into the ObservationResultsRaw structure.
    """
    max_reached     : bool  = False
    users_set       : set   = field(default_factory=set)
    obs_id_set      : set   = field(default_factory=set)

    @staticmethod
    def _unpack_observation(data) -> list[dict]:
        """
        Structure an iNaturalist observation JSON response into a list of dictionaries.
        """
        long = data.get("geojson", {}).get("coordinates", [None, None])[0] # geojson has long first
        lat = data.get("geojson", {}).get("coordinates", [None, None])[1]

        private_geojson = data.get("private_geojson")
        long_private = (
            private_geojson.get("coordinates", [None, None])[0]
            if private_geojson
            else None
        )
        lat_private = (
            private_geojson.get("coordinates", [None, None])[1]
            if private_geojson
            else None
        )

        community_taxon_id = data.get("community_taxon_id")
        obs_taxon_id = data.get("taxon", {}).get("id")
        taxon_id = community_taxon_id if community_taxon_id is not None else obs_taxon_id

        if community_taxon_id is None:
            logger.warning(
                "Observation %s has no community taxon - falling back to observation taxon %s.",
                data.get("id"), obs_taxon_id
            )

        observation = {
            "observation_id"                : data.get("id"),
            "uuid"                          : data.get("uuid"),
            "observer_id"                   : data.get("user", {}).get("id"),
            "taxon_id"                      : taxon_id,
            "license"                       : data.get("license_code"),
            "latitude"                      : lat,
            "longitude"                     : long,
            "latitude_private"              : lat_private,
            "longitude_private"             : long_private,
            "coordinate_precision"          : data.get("positional_accuracy"),
            "coordinate_precision_public"   : data.get("public_positional_accuracy"),
            "observed_on"                   : data.get("observed_on"),
            "observed_on_string"            : data.get("observed_on_string"),
            "created_at"                    : data.get("created_at"),
            "updated_at"                    : data.get("updated_at"),
            "quality_grade"                 : data.get("quality_grade"),
            "url"                           : data.get("uri"),
            "description"                   : data.get("description"),
            "id_agreements"                 : data.get("num_identification_agreements"),
            "id_disagreements"              : data.get("num_identification_disagreements"),
            "captive_cultivated"            : data.get("captive"),
            "place_guess"                   : data.get("place_guess"),
            "place_guess_private"           : data.get("place_guess_private"),
            "obscured"                      : data.get("obscured"),
            "has_photo"                     : len(data.get("photos", [])) > 0,
            "has_recording"                 : len(data.get("sounds", [])) > 0
        }
        return observation

    @staticmethod
    def _unpack_identifications(
        observation_id: int,
        ident_list: list[dict],
        user_set: set
    ) -> tuple[list, list]:
        """
        Extracts dictionaries of identifications and new users from an observation's 
        identification list.

        Args:
            observation_id:
                The id of this observation, which will be added to the identification record as a 
                foreign key.
            ident_list:
                List of identification objects from the JSON response for this observation
            user_set:
                Set of user IDs that have already been encountered.
        Returns:
            (identifications, users):
                A tuple of two lists: a list of dictionaries with identifications for this 
                observation, and a list of dictionaries with the users who made the 
                identifications (only including users not yet in the user_set).
        """
        if not ident_list:
            return [], []

        identifications = []
        users = []

        for identification in ident_list:
            # Identification does not have taxon ID, skip it
            taxon_id = identification.get("taxon", {}).get("id")
            if not taxon_id:
                logger.debug("**Identification with null taxon: %s**", identification)
                continue

            user = identification.get("user", {})
            user_id = user.get("id")
            new_identificaion = {
                "observation_id"    : observation_id,
                "user_id"           : user_id,
                "identification_id" : identification.get("id"),
                "created_at"        : identification.get("created_at"),
                "taxon_id"          : taxon_id
            }
            
            if user_id and user_id not in user_set:
                user_set.add(user_id)
                users.append(user)
            identifications.append(new_identificaion)

        return identifications, users

    @staticmethod
    def _unpack_annotations(observation_id: int, annotation_list: list) -> Optional[list[dict]]:
        """
        Extracts dictionaries of annotations from an observation's annotation list.
        """
        if annotation_list is None or len(annotation_list) == 0:
            return None

        annotations = []
        for annotation in annotation_list:
            new_annotation = {
                "observation_id"    : observation_id,
                "annotation_id"     : annotation.get("controlled_attribute_id"),
                "value_id"          : annotation.get("controlled_value_id"),
                "user_id"           : annotation.get("user_id"),
                "vote_score"        : annotation.get("vote_score")
            }
            annotations.append(new_annotation)

        return annotations

    def unpack_results(self, new_data: list):
        """
        Extract observations, identifications, and users from `data`, a list of nested
        dictionaries, and appends them to this object's result lists.
        """
        # TODO refactor to move loop outside of method
        for result in new_data:
            # Check for duplicate observations
            obs_id = result.get("id")
            if obs_id in self.obs_id_set:
                logger.warning("Encountered duplicate observation ID: %s", obs_id)
                continue
            self.obs_id_set.add(obs_id)

            # Add new observation
            observation = ObservationUnpacker._unpack_observation(result)
            self.observations.append(observation)

            # Add annotations
            annotations = ObservationUnpacker._unpack_annotations(
                observation.get("observation_id"),
                result.get("annotations")
            )
            if annotations is not None:
                self.annotations.extend(annotations)

            # Get user who made the observation, add to users set if not already present
            obs_user = result.get("user", {})
            if obs_user.get("id") and obs_user.get("id") not in self.users_set:
                self.users_set.add(obs_user.get("id"))
                self.users.append(obs_user)

            # Add identifications
            identifications, new_users = self._unpack_identifications(
                observation.get("observation_id"),
                result.get("identifications"),
                self.users_set
            )
            self.users.extend(new_users)
            self.identifications.extend(identifications)


    def is_max_reached(self, max_observations: int) -> bool:
        """
        Returns true if the number of observations is greater than `max_observations`, and false
        otherwise
        """
        # print(f"{len(self.observations)} > {max_observations} = {len(self.observations) > max_observations}")
        return len(self.observations) > max_observations


    def update_completed_taxa(self, batch: list):
        """Update set of completed taxa"""
        self.completed_taxa.update(batch)


@dataclass
class ObservationResultsClean():
    """
    Helper class that converts the working lists in a ResultsRaw object into validated dataframes.
    * **observations**: DataFrame of iNaturalist observations.
    * **identifications**: DataFrame of identifications for the returned observations.
    * **users**: DataFrame of users, both observers and identifiers.
    * **annotations**: All of the annotations left on the observations.
    * **completed_taxa**: Set of taxon IDs for which all observations have been recieved.
    """
    observations       : pd.DataFrame = None
    identifications    : pd.DataFrame = None
    users              : pd.DataFrame = None
    annotations        : pd.DataFrame = None
    completed_taxa     : set = None

    @staticmethod
    def validate(obs: ObservationResultsRaw) -> Self | None:
        """
        Converts the observations results into dataframes and validates them. Use this instead of
        the class constructor.
        """
        if len(obs.observations) == 0:
            logger.warning("No results found.")
            return None
        
        result = ObservationResultsClean()

        result.observations = ObservationResultsClean._get_validated_df(
            obs.observations,
            ObservationSchema.from_raw
        )
        result.identifications = ObservationResultsClean._get_validated_df(
            obs.identifications,
            IdentificationsSchema.from_raw
        )
        result.users = ObservationResultsClean._get_validated_df(
            obs.users,
            UsersSchema.from_raw
        )
        result.annotations = ObservationResultsClean._get_validated_df(
            obs.annotations,
            AnnotationsSchema.validate
        )
        result.completed_taxa = obs.completed_taxa

        return result

    @staticmethod
    def _get_validated_df(data: list, func):
        if data is None or len(data) == 0:
            return None
        return func(pd.DataFrame(data))

    def convert_all_to_sqlite(self) -> ObservationResultsRaw:
        """
        Converts each dataframe to a SQLite-friendly version, using the schema's to_sqlite
        method if present.
        """
        if self.observations is None:
            raise ValueError("No observations in results.")

        result = ObservationResultsRaw()
        result.observations = (
            ObservationSchema
            .to_sqlite(self.observations)
            .to_dict(orient="records")
        )
        if self.identifications is not None:
            result.identifications = (
                IdentificationsSchema
                .to_sqlite(self.identifications)
                .to_dict(orient="records")
            )
        if self.users is not None:
            result.users = self.users.to_dict(orient="records")

        if self.annotations is not None:
            result.annotations = self.annotations.to_dict(orient="records")

        if self.completed_taxa is not None:
            result.completed_taxa = self.completed_taxa

        return result


# ---------------------------------------------------------------------------
# Observation Downloader
# ---------------------------------------------------------------------------
class ObservationDownloader():
    """
    Responsible for the downloading observations from iNaturalist. Tracks download stats.
    """
    def __init__(self, cfg: config.ObservationsConfig, auth: INaturalistAuth):
        self.auth: INaturalistAuth = auth
        self.config: config.ObservationsConfig = cfg

        # Stats
        self.total_taxa_count       : int = 0
        self.request_count          : int = 0
        self.filtered_taxa_count    : int = 0
        self.unfiltered_taxa_count  : int = 0
        self.taxa_completed         : int = 0
        self.max_reached            : bool = False

        # Results
        self.results: ObservationResultsClean = None

    @staticmethod
    def _get_batches(full_list: list, batch_size: int):
        """Helper function to yield successive n-sized chunks from list"""
        full_list.sort()
        for i in range(0, len(full_list), batch_size):
            yield full_list[i:i + batch_size]

    @staticmethod
    def _create_date_taxon_map(taxa_df: pd.DataFrame) -> dict[str: set]:
        """
        Creates a map that groups taxon_ids into sets with date_updated as the key.
        Args:
            taxa_df: 
                Taxa dataframe to create a date map from
        Returns:
            Dictionary that maps a date string to a set of taxon IDs.
        """
        df = taxa_df.sort_values(by="taxon_id", ascending=True).copy()

        # Convert date to string        
        try:
            df["date_updated"] = df["date_updated"].dt.strftime(DATE_FORMAT)
        except AttributeError as ex:
            raise AttributeError("date_updated field must be of type pd.Timestamp") from ex
        except KeyError as ex:
            raise KeyError("taxa_df must have date_updated field") from ex

        date_taxon_map: dict = (
            df
            .groupby("date_updated")["taxon_id"]
            .apply(set)
            .to_dict()
        )
        date_taxon_map["None"] = (
            set(df
                .loc[df["date_updated"].isna(), "taxon_id"]
                .sort_values(ascending=True)
            )
        )
        return date_taxon_map

    def _request_batch(self, ids: list, params: dict, headers: str) -> list:
        """
        Download iNaturalist observations for a list of ID. Adds to this object's request count.
        Args:
            ids:
                List of taxon IDs to download observations for.
            params:
                Base HTTP request parameters.
            headers:
                HTTP authentication headers.
        Returns:
            A list of result dictionaries decoded from the HTTP response.
        """
        params["taxon_id"] = ",".join(str(id) for id in ids)
        url = "https://api.inaturalist.org/v2/observations"

        result, count = helpers.sliding_page_requests(url, params, headers)
        self.request_count += count

        return result

    # def _apply_date_filter(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """
    #     Filters the dataframe for taxa that were last updated more than update_days ago. If
    #     update_days is zero or None, set all taxas' date_updated column to None.
    #     """
    #     df = df.copy()
    #     # If days_updated is zero, update all taxa without a date filter.
    #     if not self.config.update_after_days:
    #         df["date_updated"] = None

    #     # Filter for taxa queried more than days_updated before now
    #     else:
    #         target_date = dt.date.today() - dt.timedelta(days=self.config.update_after_days)
    #         date_mask = pd.to_datetime(df["date_updated"]) <= pd.Timestamp(target_date)
    #         df = df[(df["date_updated"].isna()) | date_mask]

    #     return df

    @staticmethod
    def _get_fields_rison() -> str:
        """
        Helper function that reads the contents of the provided JSON file and returns a RISON
        encoded string.
        """
        try:
            with open(FIELDS_FILE_PATH, "r", encoding="latin-1") as fp:
                fields_dict = json.load(fp)

        except FileNotFoundError as ex:
            raise ValueError(f"Fields JSON file not found: {FIELDS_FILE_PATH}") from ex

        except json.JSONDecodeError as ex:
            raise ValueError(f"Failed to parse fields JSON file: {FIELDS_FILE_PATH}") from ex

        return prison.dumps(fields_dict)

    # Fetch Observations
    def fetch_observations(
            self,
            taxa_df: DataFrame[INatTaxaSchema]
    ) -> ObservationUnpacker:
        """
        Downloads observations of taxa in taxa_df from iNaturalist and structures the results
        into observations, identifications, users, and the set of taxa searched for.
        Args:
            auth:
                iNaturalist authentication object with an active access token
            taxa_df:
                Non-empty dataframe of iNaturalist taxa to search observations for. Must conform to
                schemas.INatTaxaSchema.
        Returns:
            ObservationResults object.
        Raises:
            TypeError: If taxa_df is not a dataframe.
            ValueError: If taxa_df is an empty dataframe.
        """
        # Ensure argument is a dataframe
        if not isinstance(taxa_df, pd.DataFrame):
            raise TypeError("Argument must be a dataframe.")

        # Validate dataframe
        try:
            INatTaxaSchema.validate(taxa_df)
        except SchemaError as ex:
            helpers.report_schema_error(ex)

        # Make sure dataframe is not empty
        if len(taxa_df) == 0:
            raise ValueError("No taxa to download for.")

        # Set up base parameters
        base_params = {
            'place_id'          : self.config.place_id,
            'quality_grade'     : self.config.quality_grade,
            'per_page'          : self.config.per_page,
            'order_by'          : 'id',
            'order'             : 'asc',
        }
        base_params["fields"] = self._get_fields_rison()
        if self.config.project_id:
            base_params["project_id"] = self.config.project_id

        # Create date taxa map
        date_taxa_map = self._create_date_taxon_map(taxa_df)

        # Iterate through taxon IDs and run requests
        unpacker = ObservationUnpacker()
        self.max_reached = False

        logger.debug("Base parameters:")
        for param, value in base_params.items():
            logger.debug("  %s: %s", param, value)

        for date, ids in date_taxa_map.items():
            logger.debug("")
            if date != "None":
                logger.debug("Processing taxa with 'created after' date filter: %s", str(date))
                base_params['created_d1'] = date
            else:
                logger.debug("Processing taxa with no 'created after' date filter")
                base_params.pop('created_d1', None)

            batches = self._get_batches(list(ids), self.config.batch_size)
            for i, batch in enumerate(batches, start=1):
                logger.debug("* Processing batch #%i with %i taxa...", i, len(batch))
                data = self._request_batch(
                    batch, base_params.copy(), self.auth.get_auth_headers()
                )
                logger.debug("  Finished downloading %i results.", len(data))

                unpacker.unpack_results(data)
                unpacker.update_completed_taxa(batch)
                self.max_reached = unpacker.is_max_reached(self.config.max_observations)

                if self.max_reached:
                    break

            if self.max_reached:
                break

        self.taxa_completed = len(unpacker.completed_taxa)

        return unpacker


    def run(self, taxa_df: DataFrame[INatTaxaSchema]):
        """
        Download observations for the given taxa. Performs iNaturalist API requests, unpacks and
        validates results.
        """
        # Validate taxa schema
        try:
            validated_df = INatTaxaSchema.validate(taxa_df)
        except SchemaError as ex:
            helpers.report_schema_error(ex)

        # Filter out parent/genus level matches
        match_df = INatTaxaSchema.filter_match_type(validated_df)

        # Apply date filter
        filtered_df = INatTaxaSchema.apply_date_filter(
            match_df, self.config.update_after_days, dt.date.today()
        )

        # Set stats
        self.total_taxa_count = len(validated_df)
        self.non_exact_match_count = self.total_taxa_count - len(match_df)
        self.filtered_taxa_count = len(filtered_df)
    
        # Check if there are actually taxa to be searched for
        if len(filtered_df) == 0:
            logger.warning("No taxa left to download observations for. " +
                "All taxa are either undescribed or have been updated less than %s days ago.",
                self.config.update_after_days)
            return None
    
        logger.info("* Total taxa with iNaturalist mapping: %i", self.total_taxa_count)
        logger.info("* Non-exact matches (will be skipped when downloading): %i",
            self.non_exact_match_count)
        logger.info("* Number of taxa to be updated: %i", self.filtered_taxa_count)
        logger.info("")
    
        # Download
        unpacked_results = self.fetch_observations(filtered_df)
        self.taxa_remaining = self.filtered_taxa_count - self.taxa_completed
    
        # Validate
        try:
            self.results = ObservationResultsClean.validate(unpacked_results)
        except SchemaError as ex:
            raise ValueError("Results of observations query don't fit the expected schema.") from ex
        except ValueError as ex:
            raise ValueError("Unexpected exception while structuring observation data.") from ex

        return self.results
