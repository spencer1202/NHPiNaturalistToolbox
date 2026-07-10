"""
Pipeline logic for iNaturalist Data Pipeline tool.
Handles orchestration between client, database, and validation layers.
"""
# Standard imports
import logging
import sqlite3
from typing import Self, Optional

# Third-party imports
import pandas as pd
import pandera as pa

# Local imports
from inatdatapipeline import db
from inatdatapipeline.client import (
    annotations,
    authentication,
    helpers,
    observations,
    review,
    taxa
)
from inatdatapipeline.schemas import (
    config,
    validation
)

logger = logging.getLogger('pipeline')

# ---------------------------------------------------------------------------
# Taxa
# ---------------------------------------------------------------------------

def get_tracking_dfs(
        tracking_file: str,
        overrides_file: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Helper function that loads the tracking list and list of overrides and validates their
    schemas, catching specific exceptions and re-raising them as ValueErrors.
    """
    try:
        tracking_df = pd.read_csv(tracking_file, encoding="latin-1")
        tracking_df = (
            validation.TrackingSchemaClean.from_raw(
                validation.TrackingSchemaRaw(tracking_df)
            )
        )
        overrides_df = pd.read_csv(overrides_file, encoding="latin-1")
        overrides_df = validation.OverridesSchema(overrides_df)

    except FileNotFoundError as ex:
        raise (
            ValueError("Encountered error while loading overrides and/or tracking list.")
        ) from ex

    except pa.errors.SchemaError as ex:
        raise ValueError("Invalid schema.") from ex

    return tracking_df, overrides_df


def get_existing_mappings(
        db_manager: db.DBManager,
) -> Optional[pd.DataFrame]:
    """
    Helper function that handles the logic for loading existing taxon mappings.

    Args:
        db_manager: Database manager object.
    
    Returns:
        A dataframe of taxon mappings if they're present in the database, or None if no mappings
        are found.
    """
    logger.info("Loading existing mappings...")
    try:
        with db_manager as conn:
            mapping_df = conn.select("mappings")
    except sqlite3.Error as ex:
        raise ValueError("Failed to load mappings.") from ex

    if len(mapping_df) == 0:
        logger.warning("No existing mappings found.")
        mapping_df = None

    return mapping_df



def build_taxon_mapping(
        cfg_taxa    : config.TaxaConfig,
        db_manager  : db.DBManager,
        auth        : authentication.INaturalistAuth,
        rebuild     : bool = False
):
    """
    Build a taxon mapping from the tracking list and insert results into the database.

    Loads and validates the tracking list and name overrides files. Prepares the tracking list by 
    applying name overrides, preprocessing scientific names, and marking undescribed taxa. Queries
    iNaturalist to map each tracked taxon to its corresponding iNaturalist ID and name. Inserts
    new mappings into the database, alongside any alternative taxon names.

    By default, existing mappings are preserved and only new taxa are mapped. Set rebuild=True to
    remap all taxa from scratch.

    Args:
        cfg_taxa: Taxa configuration.
        db_manager: Database manager object.
        auth: iNaturalist authentication object
        rebuild: If True, rebuild the full mapping from scratch rather than updating. Defaults to
        False.
    
    Raises:
        ValueError: If the tracking list or overrides file can't be loaded, if either fails schema
        validation, if any database operation fails.
    """
    # Load, validate and clean tracking list & overrides file
    tracking_df, overrides_df = (
        get_tracking_dfs(cfg_taxa.tracking_list, cfg_taxa.name_overrides_file)
    )

    # Insert name overrides, preprocess names, and identify undescribed taxa
    logger.debug("Preprocessing tracking list...")
    tracking_df = taxa.TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)

    # Insert tracking list into database
    logger.debug("Inserting tracking list into database...")
    try:
        with db_manager as conn:
            tracking_count = conn.insert_tracking(tracking_df)
    except sqlite3.Error as ex:
        raise ValueError("Failed to insert tracking list into database.") from ex
    logger.debug("* Inserted/updated %i taxa from the tracking list.", tracking_count)

    # Load existing mappings
    mapping_df = None if rebuild else get_existing_mappings(db_manager)
    if mapping_df is None:
        logger.info("Rebuilding taxon mappings from scratch.")
    else:
        logger.debug("Retrieved %i taxon mappings from database.", len(mapping_df))

    # Generate new mappings
    override_id_map = taxa.TaxonMappingBuilder.build_override_id_map(overrides_df)
    to_match = taxa.TaxonMappingBuilder.get_to_match(tracking_df, mapping_df)

    if len(to_match) == 0:
        logger.warning("All taxa on tracking list are already present in mappings.")
        return
    logger.debug(
        "Found %i tracking list entries not present in existing mappings.",
        len(to_match)
    )
    logger.info("Beginning taxon queries...")
    result: taxa.MappingResult = (
        taxa.TaxonMappingBuilder.get_new_mappings(auth, to_match, override_id_map)
    )

    # No new taxa or alternative names.
    if result is None:
        logger.info("No new mappings found.")
        return

    # Validate mappings
    new_mappings_clean = validation.TaxonMappingSchema.validate(result)

    # Insert mappings into database
    try:
        with db_manager as conn:
            mappings_count = conn.insert_mappings(new_mappings_clean)

    except sqlite3.Error as ex:
        raise ValueError("Failed to insert mappings into database.") from ex

    # Log results
    if mappings_count:
        logger.info("Inserted %i new mappings.", mappings_count)
    else:
        logger.info("No new mappings inserted.")


# ---------------------------------------------------------------------------
# Observations
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


    def to_sqlite(self) -> observations.ObservationResults:
        """
        Converts each dataframe to a SQLite-friendly version, using the schema's to_sqlite
        method if present.
        """
        result = observations.ObservationResults()
        result.observations = (
            validation.ObservationSchema
            .to_sqlite(self.observations)
            .to_dict(orient="records")
        )
        result.identifications = (
            validation.IdentificationsSchema
            .to_sqlite(self.identifications)
            .to_dict(orient="records")
        )
        result.users = self.users.to_dict(orient="records")
        result.annotations = self.annotations.to_dict(orient="records")
        result.completed_taxa = self.completed_taxa

        return result


    @staticmethod
    def validate(obs: observations.ObservationResults) -> Self:
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


def get_observations(
        cfg_obs: config.ObservationsConfig,
        db_manager: db.DBManager,
        auth: authentication.INaturalistAuth
):
    """
    Fetch observations from iNaturalist and insert them into the database.

    Retrieves taxon mappings from the database, filters out undescribed taxa, then downloads
    observations for each taxon. Observations are structured into their component tables: 
    observations, identifications, users, and annotations. Ensures annotation options and
    project members are up to date in the database before inserting results.

    Raises:
        ValueError: If there are no taxa in the database, if a databaase operation fails, or if a
        network request fails.
    """
    logger.info("Downloading observations...")
    logger.info("* Update if last searched before: %s days ago", cfg_obs.update_after_days)
    logger.info("* Maximum number of observations to download: %i", cfg_obs.max_observations)
    logger.info("* Project ID: %i", cfg_obs.project_id)

    # Get iNat taxa from database
    try:
        with db_manager as conn:
            taxa_df = conn.select("mappings")
    except sqlite3.Error as err:
        raise ValueError from err

    # Filter out undescribed taxa
    total_taxa_count = len(taxa_df)
    logger.info("* Total taxa with known iNaturalist entry: %i", total_taxa_count)
    taxa_df = taxa_df[taxa_df["is_described"] == 1]
    logger.info("* Undescribed taxa: %i", total_taxa_count - len(taxa_df))
    logger.info("")

    # Make sure taxa df isn't empty
    if len(taxa_df) == 0:
        raise ValueError("No taxa found in database to download!")

    # Download observations
    results: observations.ObservationResults = (
        observations.fetch_observations(auth, taxa_df, cfg_obs)
    )

    if results is None:
        logger.warning(
            "All taxa have already been updated in the past %s days. " +
            "Try changing update_after_days in the config file, or run with " +
            "'--days-since-update' option."
            , cfg_obs.update_after_days
        )
        return

    logger.info("Finished downloading!")
    logger.info("")

    # Validate results
    try:
        results_clean: ObservationResultsValidator = (
            ObservationResultsValidator.validate(results)
        )
        results_sqlite: observations.ObservationResults = results_clean.to_sqlite()
    except pa.errors.SchemaError as ex:
        raise ValueError("Results of observations query don't fit the expected schema.") from ex

    db_manager.insert_observation_results(results_sqlite)


# ---------------------------------------------------------------------------
# Update Project Members
# ---------------------------------------------------------------------------

def update_project_members(
        cfg_obs: config.ObservationsConfig,
        db_manager: db.DBManager,
        auth: authentication.INaturalistAuth
):
    """
    Fetches list of project members from iNaturalist and inserts it into the database.
    """
    logger.info("Updating project members...")
    logger.info("* Project ID: %s", cfg_obs.project_id)
    logger.info("")

    member_ids = helpers.fetch_project_members(auth, cfg_obs.project_id)
    logger.debug("Found %i project members.", len(member_ids))

    try:
        with db_manager as conn:
            rows_inserted = conn.replace_project_members(member_ids)
    except sqlite3.Error as ex:
        raise ValueError from ex

    logger.info("Inserted %i member IDs into database.", rows_inserted)


# ---------------------------------------------------------------------------
# Load annotations
# ---------------------------------------------------------------------------

def update_annotations(
        db_manager: db.DBManager,
        auth: authentication.INaturalistAuth
):
    """
    Fetches annotation categories and values from iNaturalist and inserts them into the database.
    Args:
        db_manager: Database manager object.
        auth: iNaturalist authentication object
    Raises:
        ValueError: When request network exception occurs or when a database exception occurs.
    """
    logger.info("Loading annotation options...")
    logger.info("")

    try:
        with db_manager as conn:
            result: annotations.AnnotationOptions = annotations.fetch_annotations(auth)
            count = conn.update_annotations(result)

    except sqlite3.Error as ex:
        raise ValueError("Database exception occurred while updating annotations.") from ex

    except ValueError as ex:
        raise ValueError("Network exception occurred while requesting annotations.") from ex

    logger.debug("Fetched %i annotation options and values.", count)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def update_experts(experts_file: str, db_manager: db.DBManager) -> pd.DataFrame:
    """
    Load experts from file, validate the data, and insert the experts into the database.

    Args:
        experts_file: File path of experts list. See validation.EXPERTS_INAT_ID_FIELD and 
        validation.EXPERTS_EXPERTISE_FIELD for expected raw column names.

        db_manager: Database manager object.
    
    Returns:
        Experts dataframe. See validation.ExpertsSchema for resulting schema.
    
    Raises:
        TODO update
    """
    experts_df = pd.read_csv(experts_file, encoding="utf-8")
    experts_clean_df = validation.ExpertsSchema.from_raw(experts_df)

    with db_manager as conn:
        count = conn.update_experts(experts_clean_df)

    logger.info("Inserted %i experts.", count)

    return experts_clean_df


def _get_data(db_manager: db.DBManager) -> tuple[set, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Helper function that loads and validates the data needed for the review. 

    Loads project members, expert identifications, observations, and annotations from the
    database and catches exceptions. Makes sure project members and annotation options have
    been loaded. Validates observations and expert identifications against their respective
    schemas.

    Raises:
        ValueError: If a database error occurs, project members or annotations haven't been
        loaded, or if there are no observations or expert identifications in the database.
    """
    try:
        with db_manager as conn:
            project_members_df  : pd.DataFrame = conn.select("project_members")
            expert_ids_df       : pd.DataFrame = conn.get_expert_identifications()
            observations_df     : pd.DataFrame = conn.select("full_observations")
            annotations_df      : pd.DataFrame = conn.select("annotations_with_labels")
            has_annotations     : bool = bool(len(conn.select("annotation_options")))

        # Make sure project members have been loaded properly
        if project_members_df is None or len(project_members_df) == 0:
            raise ValueError(
                "No project members in database. Try running the update-members command first."
            )
        project_members_set: set = set(project_members_df["user_id"])

        # Make sure annotations have been loaded
        if not has_annotations:
            raise ValueError(
                "iNaturalist annotations haven't been loaded. Try running the " +
                "update-annotations command first."
            )

        # Validate observations and expert IDs
        if observations_df is None or len(observations_df) == 0:
            raise ValueError("No observations present in database.")
        if expert_ids_df is None or len(expert_ids_df) == 0:
            raise ValueError("No expert identifications present in database.")

        observations_clean_df = validation.FullObservationSchema.from_sqlite(observations_df)
        expert_ids_clean_df = validation.ExpertIDsSchema.from_sqlite(expert_ids_df)

    except sqlite3.Error as ex:
        raise ValueError("Database error occurred while running review.") from ex

    except pa.errors.SchemaError as ex:
        raise ValueError("Data from the database didn't follow expected schemas.") from ex

    return (
        project_members_set,
        expert_ids_clean_df,
        observations_clean_df,
        annotations_df
    )


def run_review(
        cfg_review: config.ReviewConfig,
        db_manager: db.DBManager,
) -> pd.DataFrame:
    """
    Runs the full review and returns the resulting observations dataframe.

    Updates the experts list using the experts file in the configuration, then retrieves 
    observations, expert identifications, project members, and annotations from the database. 
    Compiles each observation's annotations into a single text column, adds a column that
    indicates expert agreement on the primary identification, adds columns with information
    on the expert identifications, and evaluates whether the observation has the required 
    licenses.

    Args:
        cfg_review: Review configuration.
        db_manager: Database manager object.
    
    Returns:
        Dataframe of reviewed observations.
    
    Raises:
        ValueError: If any database operation fails.
    """
    logger.info("Running review...")
    logger.info("* Export file: %s", cfg_review.export_csv)
    logger.info("* Experts file: %s", cfg_review.experts_file)
    logger.info("")
    # Update experts
    logger.info("Loading experts list...")
    update_experts(cfg_review.experts_file, db_manager)

    logger.info("Loading observation data from database...")
    (
        project_members_set,
        expert_ids_df,
        observations_df,
        annotations_df
    ) = _get_data(db_manager)

    # Clean expert names
    # Fill in identifier_name column with the user's name if present, otherwise use the login

    reviewer = review.Review(observations_df)

    logger.info("Running review...")
    expert_ids_df["identifier_name"] = reviewer.clean_names(expert_ids_df)
    reviewer.compile_annotations(annotations_df)
    reviewer.evaluate_expert_agreement(expert_ids_df)
    reviewer.add_identified_by(expert_ids_df)
    reviewer.add_identification_references(expert_ids_df)
    reviewer.evaluate_licenses(project_members_set)

    logger.info("Exporting reviewed observations...")
    reviewer.export(cfg_review.export_csv)
