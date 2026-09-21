"""
Pipeline logic for iNaturalist Data Pipeline tool.
Handles orchestration between client, database, and validation layers.
"""
# Standard imports
import logging
import sqlite3
from typing import Optional
import datetime as dt

# Third-party imports
import pandas as pd
import pandera as pa

# Local imports
from inatdatapipeline.database import db, gdb_export
from inatdatapipeline.schemas import (
    config,
    validation
)
from inatdatapipeline.client import (
    annotations,
    authentication,
    helpers,
    observations,
    review,
    taxa
)

logger = logging.getLogger('pipeline')

EXPORT_FORMAT_CSV = "CSV File"
EXPORT_FORMAT_FC = "Feature Class"

# ---------------------------------------------------------------------------
# Taxa
# ---------------------------------------------------------------------------

def get_tracking_dfs(
        tracking_file: str,
        overrides_file: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Helper function that loads the tracking list and list of overrides and validates their
    schemas, catching specific exceptions and re-raising them as ValueErrors. Also raises 
    ValueError if the tracking list is empty
    """
    try:
        tracking_df = pd.read_csv(tracking_file, encoding="latin-1")
        if tracking_df is None or len(tracking_df) == 0:
            raise ValueError("Tracking list is empty!")

        raw_df = validation.TrackingSchemaRaw(tracking_df)
        clean_tracking_df = validation.TrackingSchemaClean.from_raw(raw_df)

        overrides_df = pd.read_csv(overrides_file, encoding="latin-1")
        overrides_df = validation.OverridesSchema(overrides_df)

    except FileNotFoundError as ex:
        raise (
            ValueError("Encountered error while loading overrides and/or tracking list.")
        ) from ex

    except pa.errors.SchemaError as ex:
        logger.error("Schema name: %s", ex.schema.name)
        logger.error("Failed check: %s", ex.check)
        logger.error("Bad values: %s", ex.failure_cases)
        raise ValueError("Invalid schema.") from ex

    return clean_tracking_df, overrides_df


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


def fetch_mapping(
        builder: taxa.TaxonMappingBuilder,
        tracking_df: pd.DataFrame,
        overrides_df: pd.DataFrame,
        old_mappings_df: pd.DataFrame = None
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Runs the entire taxon mapping build from start to finish, including preprocessing the
    tracking and overrides lists, filtering out existing mappings, creating the mappings,
    and validating them.

    Args:
        tracking_df: A tracking list dataframe conforming to validation.TrackingSchemaClean
        overrides_df: An overrides list dataframe conforming to validation.OverridesSchema
        old_mappings_df: A dataframe with existing mappings
    
    Returns:
        (clean_tracking_df, new_mappings_clean): A tuple containing a preprocessed tracking
        list dataframe and a dataframe of new validated mappings. Both are None if all 
        tracking list taxa already have mappings, and new_mappings_clean is None if no new
        mappings were found.

    """
    # Insert name overrides, preprocess names, and identify undescribed taxa
    logger.debug("Preprocessing tracking list...")
    clean_tracking_df = builder.preprocess_tracking_df(tracking_df, overrides_df)

    # Filter tracking list
    override_id_map = builder.build_override_id_map(overrides_df)
    to_match = builder.get_to_match(clean_tracking_df, old_mappings_df)

    if len(to_match) == 0:
        logger.warning("All taxa on tracking list are already present in mappings.")
        return None, None

    logger.debug(
        "Found %i tracking list entries not present in existing mappings.",
        len(to_match)
    )
    logger.info("Beginning taxon queries...")

    # Generate new mappings
    result = builder.create_new_mappings(to_match, override_id_map)

    # No new taxa.
    if len(result) == 0:
        logger.info("No new mappings found.")
        return clean_tracking_df, None

    # Validate mappings
    new_mappings_clean = taxa.TaxonMappingSchema.validate(result)
    return clean_tracking_df, new_mappings_clean


def build_taxon_mapping(
        tracking_csv: str,
        overrides_csv: str,
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
        tracking_csv: File path of tracking list.
        overrides_csv: File path of name overrides list.
        db_manager: Database manager object.
        auth: iNaturalist authentication object
        rebuild: If True, rebuild the full mapping from scratch rather than updating. Defaults to
        False.

    Raises:
        ValueError: If the tracking list or overrides file can't be loaded, if either fails schema
        validation, if any database operation fails.
    """
    logger.info("Building taxon map...")
    logger.info("* Tracking list file: %s", tracking_csv)
    logger.info("* Overrides list file: %s", overrides_csv)
    logger.info("")

    # Load existing mappings
    old_mappings_df = None if rebuild else get_existing_mappings(db_manager)
    if old_mappings_df is None:
        logger.info("Rebuilding taxon mappings from scratch.")
    else:
        logger.debug("Retrieved %i taxon mappings from database.", len(old_mappings_df))

    # Load, validate and clean tracking list & overrides file.
    tracking_df, overrides_df = (
        get_tracking_dfs(tracking_csv, overrides_csv)
    )

    builder = taxa.TaxonMappingBuilder(auth)
    result = fetch_mapping(builder, tracking_df, overrides_df, old_mappings_df)

    # No new tracking list taxa to search for
    if result[0] is None:
        return

    logger.info("")
    logger.info("Search complete.")
    logger.info("* Request count: %s", builder.request_count)

    logger.debug("Inserting results into database...")
    update_db_with_mappings(db_manager, builder.request_count, result[0], result[1])


def update_db_with_mappings(
        db_manager: db.DBManager,
        requests_today: int,
        tracking_df: pd.DataFrame,
        new_mappings: Optional[pd.DataFrame]
):
    """
    Inserts mappings, tracking list, and request count into the database, handles exceptions, and
    logs results.
    """
    today = dt.date.today()
    try:
        with db_manager as conn:
            # Update request count
            total_requests = conn.get_request_count(today) + requests_today
            conn.update_request_count(total_requests, today)

            # Insert tracking list and mappings
            tracking_count = conn.insert_tracking(tracking_df)
            mapping_count = conn.insert_mappings(new_mappings) if new_mappings is not None else 0

    except sqlite3.Error as ex:
        raise ValueError("Failed to update database.") from ex

    # Log results
    logger.info("* Total requests today (%s): %s", today, total_requests)
    logger.debug("* Inserted/updated %i taxa from the tracking list.", tracking_count)
    if mapping_count:
        logger.info("* Inserted %i new mappings.", mapping_count)
    else:
        logger.info("* No new mappings inserted.")


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

def log_obs_download_results(
        results: observations.ObservationResults,
        downloader: observations.ObservationDownloader,
        prev_request_count: int
) -> int:
    """
    Logs observation download stats and returns the total number of requests made today.
    """
    # No requests made
    if len(results.observations) == 0 and downloader.request_count == prev_request_count:
        logger.info("No searches performed.")
        return 0

    logger.info("Search complete.")

    today = dt.date.today()
    total_requests = downloader.request_count + prev_request_count
    logger.info("* Request count: %s", downloader.request_count)
    logger.info("* Total requests today (%s): %s", today, total_requests)

    if len(results.observations) == 0:
        logger.info("* No results found.")
        return 0

    logger.info("* Taxa searched for: %s", downloader.taxa_completed)
    logger.info("* Exceeded max download count: %s", downloader.exceeded_download_max)
    logger.info("* Remaining unupdated taxa: %s", downloader.taxa_remaining)
    logger.info("")

    return total_requests


def get_observations(
        cfg_obs: config.ObservationsConfig,
        db_manager: db.DBManager,
        auth: authentication.INaturalistAuth
):
    """
    Fetch observations from iNaturalist and insert them into the database.

    Retrieves taxon mappings from the database, filters out parent/genus level matches, then
    downloads observations for each taxon. Observations are structured into their component tables:
    observations, identifications, users, and annotations. Ensures annotation options and
    project members are up to date in the database before inserting results.

    Raises:
        ValueError: If there are no taxa in the database, if a databaase operation fails, or if a
        network request fails.
    """
    logger.info("Downloading observations...")
    logger.info("* Update if last searched before: %s days ago", cfg_obs.update_after_days)
    logger.info("* Maximum number of observations to download: %i", cfg_obs.max_observations)
    if not cfg_obs.project_id:
        logger.info("* No project ID filter.")
    else:
        logger.info("* Project ID: %i", cfg_obs.project_id)
    logger.info("* Place ID: %s", cfg_obs.place_id)

    today = dt.date.today()

    # Get iNat taxa and request count from database
    try:
        with db_manager as conn:
            taxa_df = conn.select("mappings")
            prev_request_count = db_manager.get_request_count(today)
    except sqlite3.Error as err:
        raise ValueError from err

    downloader = observations.ObservationDownloader(cfg_obs, auth)

    # Filter out taxa we don't want to download observations for
    taxa_df = downloader.filter_taxa(taxa_df)

    # Check if there are actually taxa to be searched for
    if len(taxa_df) == 0:
        logger.warning("No taxa left to download observations for. " +
            "All taxa are either undescribed or have been updated less than %s days ago.",
            cfg_obs.update_after_days)
        return

    logger.info("* Total taxa with iNaturalist mapping: %i", downloader.total_taxa_count)
    logger.info("* Non-exact matches (will be skipped when downloading): %i",
        downloader.undescribed_taxa_count)
    logger.info("* Number of taxa to be updated: %i", downloader.filtered_taxa_count)
    logger.info("")

    # Download
    results = downloader.fetch_observations(taxa_df)
    total_requests = log_obs_download_results(results, downloader, prev_request_count)

    if len(results.observations) == 0:
        return

    # Validate
    try:
        results_clean: observations.ObservationResultsValidator = (
            observations.ObservationResultsValidator.validate(results)
        )
        results_sqlite: observations.ObservationResults = results_clean.to_sqlite()
    except pa.errors.SchemaError as ex:
        raise ValueError("Results of observations query don't fit the expected schema.") from ex

    # Insert into database
    db_manager.insert_observation_results(results_sqlite)
    with db_manager as conn:
        conn.update_request_count(total_requests, today)


# ---------------------------------------------------------------------------
# Update Project Members
# ---------------------------------------------------------------------------

def update_project_members(
        project_id: int,
        db_manager: db.DBManager,
        auth: authentication.INaturalistAuth
):
    """
    Fetches list of project members from iNaturalist and inserts it into the database.
    """
    logger.info("Updating project members...")
    logger.info("* Project ID: %s", project_id)
    logger.info("")

    member_ids = helpers.fetch_project_members(auth, project_id)
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

def update_experts(
        experts_file: str,
        id_field: str,
        expertise_field: str,
        db_manager: db.DBManager
) -> pd.DataFrame:
    """
    Load experts from file, validate the data, and insert the experts into the database.

    Args:
        experts_file: File path of experts list. See validation.EXPERTS_INAT_ID_FIELD and 
        validation.EXPERTS_EXPERTISE_FIELD for expected raw column names.
        id_field: Name of column in `experts_file` holding the iNaturalist user ID.
        expertise_field: Name of column in `experts_file` holding the expertise value.
        db_manager: Database manager object.
    
    Returns:
        Experts dataframe. See validation.ExpertsSchema for resulting schema.
    """
    experts_df = pd.read_csv(experts_file, encoding="utf-8")
    experts_clean_df = validation.ExpertsSchema.from_raw(experts_df, id_field, expertise_field)

    with db_manager as conn:
        count = conn.update_experts(experts_clean_df)

    logger.info("Inserted %i experts.", count)

    return experts_clean_df


def _get_data(
        db_manager: db.DBManager
) -> tuple[set, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
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
            raise ValueError("No project members in database.")
        project_members_set: set = set(project_members_df["user_id"])

        # Make sure annotations have been loaded
        if not has_annotations:
            raise ValueError("iNaturalist annotations haven't been loaded.")

        # Validate observations
        if observations_df is None or len(observations_df) == 0:
            raise ValueError("No observations present in database.")
        observations_clean_df = validation.FullObservationSchema.from_sqlite(observations_df)

        # Create empty expert IDs dataframe if there are no expert IDs
        if expert_ids_df is None or len(expert_ids_df) == 0:
            expert_ids_clean_df = validation.ExpertIDsSchema.empty()
        else:
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
    logger.info("* Export %s: %s", cfg_review.export_format, cfg_review.export_path)
    logger.info("* Experts file: %s", cfg_review.experts_file)
    logger.info("")
    # Update experts
    logger.info("Loading experts list...")
    update_experts(
        cfg_review.experts_file,
        cfg_review.experts_id_field,
        cfg_review.experts_expertise_field,
        db_manager
    )

    logger.info("Loading observation data from database...")
    (
        project_members_set,
        expert_ids_df,
        observations_df,
        annotations_df
    ) = _get_data(db_manager)

    logger.info("Running review...")
    reviewer = review.Reviewer(observations_df)
    reviewer.run_review(expert_ids_df, annotations_df, project_members_set)

    logger.info("Exporting reviewed observations...")

    if cfg_review.export_format == EXPORT_FORMAT_FC:
        export_df = reviewer.format_for_gdb()
        gdb_export.write_point_feature_class(
            export_df,
            cfg_review.export_path
        )
    else:
        export_df = reviewer.format_for_csv()
        export_df.to_csv(cfg_review.export_path, index=False)

    logger.info("Export finished!")
