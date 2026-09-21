"""
observations.py

This module defines the ObservationDownloader class, which uses the iNaturalist API to download
observations and their corresponding identifications, users, and annotations, then structures
the results into an ObservationResults object. ObservationResultsValidator validates those
results and converts them into SQLite-ready records.
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
import prison

#### Local imports ####
from inatdatapipeline.client import helpers
from inatdatapipeline.schemas import (
    config,
    validation
)
from inatdatapipeline.client.authentication import (
    INaturalistAuth
)

#### Setup ####
logger = logging.getLogger('pipeline')

# Location of file with observation fields to search for
FIELDS_FILE = "obs_fields.json"
fields_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), FIELDS_FILE)

# ---------------------------------------------------------------------------
# ObservationResults
# ---------------------------------------------------------------------------
@dataclass
class ObservationResults():
    """
    Structured results of the iNaturalist observation requests.
    * **observations**: DataFrame of iNaturalist observations.
    * **identifications**: DataFrame of identifications for the returned observations.
    * **users**: DataFrame of users, both observers and identifiers.
    * **annotations**: All of the annotations left on the observations.
    * **completed_taxa**: Set of taxon IDs for which all observations have been recieved.
    """
    observations    : list[dict]    = field(default_factory=list)
    identifications : list[dict]    = field(default_factory=list)
    users           : list[dict]    = field(default_factory=list)
    annotations     : list[dict]    = field(default_factory=list)
    completed_taxa  : set           = field(default_factory=set)


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
        self.request_count          : int = 0
        self.total_taxa_count       : int = 0
        self.filtered_taxa_count    : int = 0
        self.undescribed_taxa_count : int = 0
        self.taxa_completed         : int = 0
        self.exceeded_download_max  : bool = False


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

    def _apply_date_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filters the dataframe for taxa that were last updated more than update_days ago. If
        update_days is zero or None, set all taxas' date_updated column to None.
        """
        df = df.copy()
        # If days_updated is zero, update all taxa without a date filter.
        if not self.config.update_after_days:
            df["date_updated"] = None

        # Filter for taxa queried more than days_updated before now
        else:
            target_date = dt.date.today() - dt.timedelta(days=self.config.update_after_days)
            date_mask = pd.to_datetime(df["date_updated"]) <= pd.Timestamp(target_date)
            df = df[(df["date_updated"].isna()) | date_mask]

        return df

    @staticmethod
    def _get_fields_rison() -> str:
        """
        Helper function that reads the contents of the provided JSON file and returns a RISON
        encoded string.
        """
        try:
            with open(fields_file_path, "r", encoding="latin-1") as fp:
                fields_dict = json.load(fp)

        except FileNotFoundError as ex:
            raise ValueError(f"Fields JSON file not found: {fields_file_path}") from ex

        except json.JSONDecodeError as ex:
            raise ValueError(f"Failed to parse fields JSON file: {fields_file_path}") from ex

        return prison.dumps(fields_dict)

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

    @staticmethod
    def _unpack_results(data: list, all_observations: ObservationResults, users_set: set, obs_id_set: set):
        """
        Extract observations, identifications, and users from a list of nested dictionaries
        into the ObservationsResult object. Mutates all_observations and returns the updated 
        users_set and obs_id_set.
        """
        users_set = users_set.copy()
        obs_id_set = obs_id_set.copy()

        for result in data:
            # Check for duplicate observations
            obs_id = result.get("id")
            if obs_id in obs_id_set:
                logger.warning("Encountered duplicate observation ID: %s", obs_id)
                continue
            obs_id_set.add(obs_id)

            # Add new observation
            observation = ObservationDownloader._unpack_observation(result)
            all_observations.observations.append(observation)

            # Add annotations
            annotations = ObservationDownloader._unpack_annotations(
                observation.get("observation_id"),
                result.get("annotations")
            )
            if annotations is not None:
                all_observations.annotations.extend(annotations)

            # Get user who made the observation, add to users set if not already present
            obs_user = result.get("user", {})
            if obs_user.get("id") and obs_user.get("id") not in users_set:
                users_set.add(obs_user.get("id"))
                all_observations.users.append(obs_user)

            # Add identifications
            identifications, new_users = ObservationDownloader._unpack_identifications(
                observation.get("observation_id"),
                result.get("identifications"),
                users_set
            )
            all_observations.users.extend(new_users)
            all_observations.identifications.extend(identifications)

        return users_set, obs_id_set


    def filter_taxa(
            self,
            taxa_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Helper function that returns a copy of the taxa dataframe filtered for only those that
        need to be searched for.
        """
        df = taxa_df.copy()

        # Filter out parent/genus level matches
        match_type_mask = df["match_type"].isin(["exact", "override"])
        match_df = df[match_type_mask]

        # Apply date filter
        filtered_df = self._apply_date_filter(match_df)

        # Set stats
        self.total_taxa_count = len(taxa_df)
        self.undescribed_taxa_count = self.total_taxa_count - len(match_df)
        self.filtered_taxa_count = len(filtered_df)

        return filtered_df

    # Fetch Observations
    def fetch_observations(
            self,
            taxa_df: pd.DataFrame
    ) -> Optional[ObservationResults]:
        """
        Downloads observations of taxa in taxa_df from iNaturalist and structures the results
        into observations, identifications, users, and the set of taxa searched for.
        Args:
            auth:
                iNaturalist authentication object with an active access token
            taxa_df:
                Non-empty dataframe of iNaturalist taxa to search observations for.
        Returns:
            ObservationResults object.
        Raises:
            TypeError: If taxa_df is not a dataframe.
            ValueError: If taxa_df is an empty dataframe.
        """
        if not isinstance(taxa_df, pd.DataFrame):
            raise TypeError("Argument must be a pandas DataFrame.")
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
        all_observations    = ObservationResults()
        users_set           = set()
        obs_id_set          = set()
        max_reached         = False

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

                # Unpack results into all_observations
                users_set, obs_id_set = self._unpack_results(
                    data, all_observations, users_set, obs_id_set
                )

                # Update set of completed taxa
                all_observations.completed_taxa.update(batch)

                if len(all_observations.observations) > self.config.max_observations:
                    max_reached = True
                    break

            if max_reached:
                break

        self.exceeded_download_max = max_reached
        self.taxa_completed = len(all_observations.completed_taxa)
        self.taxa_remaining = self.filtered_taxa_count - self.taxa_completed

        return all_observations


# ---------------------------------------------------------------------------
# Observation Results Validator
# ---------------------------------------------------------------------------
class ObservationResultsValidator:
    """
    Helper class that converts the dataframes in an ObservationResults object (from the observations 
    module) into validated dataframes, then into sqlite-friendly formats.
    """
    def __init__(self):
        """
        Just creates an empty validator. Avoid using this, instead use the <code>validate</code> 
        static method to create an object from ObservationResults.
        """
        self.observations       : pd.DataFrame = None
        self.identifications    : pd.DataFrame = None
        self.users              : pd.DataFrame = None
        self.annotations        : pd.DataFrame = None
        self.completed_taxa     : set = None


    def to_sqlite(self) -> ObservationResults:
        """
        Converts each dataframe to a SQLite-friendly version, using the schema's to_sqlite
        method if present.
        """
        if self.observations is None:
            raise ValueError("No observations in results.")

        result = ObservationResults()
        result.observations = (
            validation.ObservationSchema
            .to_sqlite(self.observations)
            .to_dict(orient="records")
        )
        if self.identifications is not None:
            result.identifications = (
                validation.IdentificationsSchema
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


    @staticmethod
    def validate(obs: ObservationResults) -> Self:
        """
        Initializes and populates an ObservationResultsClean object with validated dataframes from
        the provided ObservationResults object. 
        """
        result = ObservationResultsValidator()
        result.observations = (
            result.get_validated_df(
                obs.observations,
                validation.ObservationSchema.from_raw
            )
        )
        result.identifications = (
            result.get_validated_df(
                obs.identifications,
                validation.IdentificationsSchema.from_raw
            )
        )
        result.users = (
            result.get_validated_df(
                obs.users,
                validation.UsersSchema.from_raw
            )
        )
        result.annotations = (
            result.get_validated_df(
                obs.annotations,
                validation.AnnotationsSchema.validate
            )
        )
        result.completed_taxa = obs.completed_taxa
        return result


    @staticmethod
    def get_validated_df(df, func, kwargs = None) -> pd.DataFrame:
        """
        Helper function that applies the given validation function to the dataframe using the 
        arguments in kwargs.
        """
        if not kwargs:
            kwargs = {}

        if df is None or len(df) == 0:
            return None

        return func(pd.DataFrame(df), **kwargs)
    