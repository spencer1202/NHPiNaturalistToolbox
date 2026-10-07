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
from pandera.pandas import errors as panderrors

# Local imports
from inatdatapipeline import config
from inatdatapipeline.database import db, gdb_export
from inatdatapipeline import (
    schemas
)
from inatdatapipeline.client import (
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
    Helper function that loads the tracking list and list of overrides. Catches exceptions and
    re-raises them as ValueErrors.
    """
    try:
        tracking_df = pd.read_csv(tracking_file, encoding="latin-1")
        overrides_df = pd.read_csv(overrides_file, encoding="latin-1")

    except FileNotFoundError as ex:
        raise (
            ValueError("Encountered error while loading overrides and/or tracking list.")
        ) from ex

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
        tracking_csv    : str,
        overrides_csv   : str,
        cfg_taxa        : config.TaxaConfig,
        db_manager      : db.DBManager,
        auth            : authentication.INaturalistAuth,
):
    """
    Build a taxon mapping from the tracking list and insert results into the database.

    Loads and validates the tracking list and name overrides files. Prepares the tracking list by 
    applying name overrides, preprocessing scientific names, and marking undescribed taxa. Queries
    iNaturalist to map each tracked taxon to its corresponding iNaturalist ID and name. Inserts
    new mappings into the database.

    By default, existing mappings are preserved and only new taxa are mapped. Set 
    cfg_taxa.rebuild=True to remap all taxa from scratch.

    Args:
        tracking_csv: File path of tracking list.
        overrides_csv: File path of name overrides list.
        cfg_taxa: Configuration settings.
        db_manager: Database manager object.
        auth: iNaturalist authentication object

    Raises:
        ValueError: If the tracking list or overrides file can't be loaded, if either fails schema
        validation, if any database operation fails.
    """

    logger.info("Building taxon map...")
    logger.info("* Tracking list file: %s", tracking_csv)
    logger.info("* Overrides list file: %s", overrides_csv)
    logger.info("")

    # Load existing mappings
    old_mappings_df = None if cfg_taxa.rebuild else get_existing_mappings(db_manager)
    # print(old_mappings_df[["est_id", "inat_name", "parent_egt_id", "genus_egt_id"]])
    
    if old_mappings_df is None:
        logger.info("Rebuilding taxon mappings from scratch.")
    else:
        logger.debug("Retrieved %i taxon mappings from database.", len(old_mappings_df))

    # Load tracking list & overrides file.
    tracking_df, overrides_df = (
        get_tracking_dfs(tracking_csv, overrides_csv)
    )

    builder = taxa.TaxonMappingBuilder(cfg_taxa, auth)
    print(tracking_df)
    builder.build(tracking_df, overrides_df, old_mappings_df)

    # No new tracking list taxa to search for
    if builder.tracking_df is None:
        return

    logger.info("")
    logger.info("Search complete.")
    logger.info("* Request count: %s", builder.request_count)

    logger.debug("Inserting results into database...")
    update_db_with_mappings(
        db_manager,
        builder.request_count,
        builder.tracking_df,
        builder.new_mappings_df
    )


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
        results: observations.ObservationResultsClean,
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
    logger.info("* Exceeded max download count: %s", downloader.max_reached)
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
    result = downloader.run(taxa_df)

    if result is None:
        return
    
    results_sqlite = result.convert_all_to_sqlite()
    total_requests = log_obs_download_results(results_sqlite, downloader, prev_request_count)

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
            categories, values = helpers.fetch_annotations(auth)
            count = conn.update_annotations(categories, values)

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
    experts_clean_df = schemas.ExpertsSchema.from_raw(experts_df, id_field, expertise_field)

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
    # dataframes = review.ReviewDataframes()
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
        observations_clean_df = schemas.FullObservationSchema.from_sqlite(observations_df)

        # Create empty expert IDs dataframe if there are no expert IDs
        if expert_ids_df is None or len(expert_ids_df) == 0:
            expert_ids_clean_df = schemas.ExpertIDsSchema.empty()
        else:
            expert_ids_clean_df = schemas.ExpertIDsSchema.from_sqlite(expert_ids_df)

    except sqlite3.Error as ex:
        raise ValueError("Database error occurred while running review.") from ex

    except panderrors.SchemaError as ex:
        raise ValueError("Data from the database didn't follow expected schemas.") from ex

    return (
        project_members_set,
        expert_ids_clean_df,
        observations_clean_df,
        annotations_df
    )


def run_review(
        experts_file: str,
        export_format: str,
        export_path: str,
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
        experts_file: File path of experts list.
        export_format: Export option, either "CSV File" for a CSV export or "Feature Class" for
            an export to a GeoDatabase feature class.
        export_path: File path of export file, either a .csv file or a feature class.
        cfg_review: Review configuration.
        db_manager: Database manager object.
    """
    logger.info("Running review...")
    logger.info("* Export %s: %s", export_format, export_path)
    logger.info("* Experts file: %s", experts_file)
    logger.info("")
    logger.info("Loading experts list...")
    
    # Update experts
    experts_df = pd.read_csv(experts_file, encoding="utf-8")

    reviewer = review.Reviewer(cfg_review)
    experts_clean_df = reviewer.validate_experts(experts_df)

    with db_manager as conn:
        count = conn.update_experts(experts_clean_df)

    logger.info("Inserted %i experts.", count)
    logger.info("Loading observation data from database...")
    (
        project_members_set,
        expert_ids_df,
        observations_df,
        annotations_df
    ) = _get_data(db_manager)

    logger.info("Running review...")
    reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members_set)

    logger.info("Exporting reviewed observations...")

    if export_format == EXPORT_FORMAT_FC:
        export_df = reviewer.format_for_gdb(reviewed_df)
        gdb_export.write_point_feature_class(
            export_df,
            export_path
        )
    else:
        export_df = reviewer.format_for_csv(reviewed_df)
        export_df.to_csv(export_path, index=False)

    logger.info("Export finished!")
