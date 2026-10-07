"""
This module is responsible for all of the data validation and transformations. It contains 
schemas defining each of the package's dataframes along with data transformation methods that 
validate all schemas at each step of transformation.
"""
from __future__ import annotations

#### Standard Imports ####
import logging
from typing import Optional
import datetime as dt
import re

#### Third-party imports ####
import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.typing import DataFrame

#### Constants ####
# String format for storing datetimes in sqlite
DATE_FORMAT = "%Y-%m-%d"
# Possible values for match_type in INatTaxaSchema
MATCH_TYPES = ['genus', 'parent', 'override', 'exact']
# Possible values for classification_level in TrackingListSchema
CLASS_LEVELS = ["Species", "Variety", "Subspecies", "Population"]
# Biotics class levels that count as "subranks" (below species-level)
BIOTICS_SUBRANKS = ["Population", "Variety", "Subspecies"]

#### Setup ####
logger = logging.getLogger("pipeline")

#### Helpers ####
def _str_to_datetime(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """
    Helper function that converts the given date columns to a naive pa.DateTime.

    Formats that iNaturalist dates come in:
        * 2016-11-15T00:30:31-08:00
        * 2026-06-11 15:04
        * 2026-06-11
    """
    pattern = r"(\d{4}-\d{2}-\d{2})"

    for col in date_cols:
        if not col in df.columns:
            raise ValueError(f"Dataframe does not contain expected column: {col}")

        # Strip timezones and hours/minutes
        df[col] = df[col].str.extract(pattern)
        # Convert to datetime
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

#### Schema ####
class OverridesSchema(pa.DataFrameModel):
    """Manual overrides for tracking list taxon names."""
    est_id      : pa.typing.Series[int]
    inat_name	: pa.typing.Series[str]
    taxon_id    : pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"

    @classmethod
    def from_raw(
        cls,
        df: pd.DataFrame,
        est_id_field: str,
        inat_name_field: str,
        taxon_id_field: str
    ) -> DataFrame[OverridesSchema]:
        renames = {
            est_id_field: "est_id",
            inat_name_field: "inat_name",
            taxon_id_field: "taxon_id"
        }
        clean_df = df.copy().rename(columns=renames)
        return cls.validate(clean_df)


@pa.check_types
def build_override_id_map(
    overrides_df: DataFrame[OverridesSchema]
) -> dict[int, int]:
    """
    Builds a dictionary that maps est_ids to override ids from an overrides dataframe.
    
    Args:
        overrides_df: Dataframe of overrides that conforms to the OverridesSchema.
    Returns:
        Dictionary that maps each est_id to its corresponding taxon id override from the
        dataframe.
    """
    just_override_ids = overrides_df.dropna(subset=["taxon_id"])
    return dict(zip(just_override_ids["est_id"], just_override_ids["taxon_id"]))



# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

#### Schema ####
class TrackingListSchema(pa.DataFrameModel):
    """Tracking list with added and renamed columns."""
    est_id                  : pa.typing.Series[int] = pa.Field(unique=True, ge=0, coerce=True)
    egt_id                  : pa.typing.Series[int] = pa.Field(unique=True, ge=0, coerce=True)
    sci_name                : pa.typing.Series[str]
    sci_name_clean          : Optional[pa.typing.Series[str]]
    global_sci_name         : pa.typing.Series[str]
    override_name           : Optional[pa.typing.Series[str]] = pa.Field(nullable=True, coerce=True)
    classification_level    : pa.typing.Series[str] = pa.Field(isin=CLASS_LEVELS)
    is_described            : Optional[pa.typing.Series[bool]] = pa.Field(coerce=True)
    parent_egt_id           : pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)
    parent_sci_name         : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    element_type            : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    common_name             : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    family                  : pa.typing.Series[str]
    genus_egt_id            : pa.typing.Series[int] = pa.Field(coerce=True)
    genus_sci_name          : pa.typing.Series[str]
    author                  : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    egt_uid                 : pa.typing.Series[str]
    srank                   : pa.typing.Series[str]
    track_status            : pa.typing.Series[str]
    explorer                : pa.typing.Series[str]
    elcode                  : pa.typing.Series[str]
    growth_habit            : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    duration                : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"      # remove extra columns

    @classmethod
    def from_raw(cls, df: pd.DataFrame) -> DataFrame[TrackingListSchema]:
        """Replaces empty strings with NaN and validates the dataframe against the schema."""
        try:
            clean_df = df.replace(r"^\s*$", np.nan, regex=True) # replace empty strings with NaN
            clean_df = clean_df.dropna(subset="est_id")
        except KeyError as ex:
            raise ValueError(f"Tracking list is missing required field.") from ex
        return cls.validate(clean_df)


    #### Check Types ####
    @classmethod
    @pa.check_types
    def run_all_preprocessing(
        cls,
        tracking_df: DataFrame[TrackingListSchema],
        overrides_df: DataFrame[OverridesSchema]
    ) -> DataFrame[TrackingListSchema]:
        """
        Preprocesses tracking dataframe. Fills in new override_name column from overrides_df, cleans
        up scientific names and creates sci_name_clean column, adds is_undescribed column, and fills in
        parent_egt_id and parent_sci_name where it's needed.
        Args:
            tracking_df: Dataframe with tracked taxa.
            overrides_df: Dataframe with name overrides.
        Returns:
            A copy of the tracking dataframe that has been preprocessed.
        """

        tracking_df = TrackingListSchema._insert_override_names(tracking_df, overrides_df)
        tracking_df = TrackingListSchema._preprocess_names(tracking_df)
        tracking_df = TrackingListSchema._mark_undescribed_taxa(tracking_df)
        tracking_df = TrackingListSchema._fill_parent(tracking_df)

        return tracking_df


    #### Helpers ####
    @staticmethod
    def _insert_override_names(
        tracking_df: DataFrame[TrackingListSchema],
        overrides_df: DataFrame[OverridesSchema]
    ) -> DataFrame[TrackingListSchema]:
        """
        Inserts the `override_name` column into a copy of `tracking_df` and returns it.
        """
        df = tracking_df.copy()

        df["override_name"] = (
            df["est_id"]
            .map(overrides_df.set_index("est_id")["inat_name"])
        )
        return df


    @staticmethod
    def _preprocess_names(
        tracking_df: DataFrame[TrackingListSchema]
    ) -> DataFrame[TrackingListSchema]:
        """
        Preprocesses `sci_name` into `sci_name_clean` and replaces `override_name` values with
        preprocessed versions.
        """
        df = tracking_df.copy()

        df["sci_name_clean"] = df["sci_name"].apply(TrackingListSchema._preprocess_name)
        df["override_name"] = df["override_name"].apply(TrackingListSchema._preprocess_name)

        return df


    @staticmethod
    def _mark_undescribed_taxa(
        tracking_df: DataFrame[TrackingListSchema],
        name_field: str = "sci_name_clean"
    ) -> DataFrame[TrackingListSchema]:
        """
        Creates `is_described` column that marks undescribed taxa.
        """
        df = tracking_df.copy()

        undescribed_names = TrackingListSchema._get_undescribed_names(df[name_field])
        df["is_described"] = (undescribed_names == "")

        return df


    @staticmethod
    def _fill_parent(
        tracking_df: DataFrame[TrackingListSchema],
    ) -> DataFrame[TrackingListSchema]:
        """
        Sometimes Biotics does not have a parent taxon for a subnational 
        population/variety/subspecies, in which case the global taxon represents the parent taxon.
        This method fills in those missing parent taxa with the global taxa.
        """
        df = tracking_df.copy()
        
        subrank_mask = df["classification_level"].isin(BIOTICS_SUBRANKS)

        df.loc[subrank_mask, "parent_egt_id"] = (
            df["parent_egt_id"]
            .loc[subrank_mask]
            .fillna(df.loc[subrank_mask, "egt_id"])
        )
        df.loc[subrank_mask, "parent_sci_name"] = (
            df["parent_sci_name"]
            .astype(object)
            .loc[subrank_mask]
            .fillna(df.loc[subrank_mask, "global_sci_name"])
        )

        return df


    @staticmethod
    def _preprocess_name(name: str) -> str:
        """
        Preprocess taxon name for iNaturalist API query by converting trinomial format
        
        Converts names like "Aster alpinus var. vierhapperi" to "Aster alpinus vierhapperi"
        which is the preferred format for iNaturalist queries.
        
        Args:
            name: Scientific name to preprocess
        Returns:
            Name with "var.", "pop.", and "ssp." removed for better iNaturalist matching
        """
        if not name or pd.isna(name):
            return None

        # Edge case: name is a single-word string, return name as is
        is_single_word = re.fullmatch(r"^[A-Za-z\-]+", name.strip())
        if is_single_word:
            logger.warning("Encountered single-word taxon name '%s'.", name.strip())
            return name.strip()

        # Regular expression that extracts the genus name, species name, and subspecies name or
        # subspecies/population number.
        expr = r"^((?:[a-zA-Z\-]+[ \t]){1,2})(?:(?:var\.|pop\.|ssp\.|sp\.)\s)?(.+)?"
        match = re.search(expr, name.strip())
        if not match:       # some weird edge case
            return None

        processed_name = match.group(1) + match.group(2)

        # Clean up any double spaces
        while "  " in processed_name:
            processed_name = processed_name.replace("  ", " ")

        return processed_name.strip()


    @staticmethod
    def _get_undescribed_names(names: pd.Series) -> pd.Series:
        """
        Extracts generic names for all undescribed taxa and returns them as a series.
        Args:
            names: Series of taxon names.

        Returns:
            A series that is populated by generic names for all undescribed taxa.

        """
        names = names.copy()

        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+)\d+$"
        result = names.str.extract(expr, expand=False).str.strip()

        # Second pass to check for single-word names
        is_single_word = names.str.fullmatch(r"[A-Za-z\-]+").fillna(False)
        result = result.fillna(names.where(is_single_word)).infer_objects(copy=False)

        return result.fillna("")


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

#### Schemas ####
class MappingsSchema(pa.DataFrameModel):
    """
    The schema of mappings pulled from the database. `est_id` is always populated.
    """
    taxon_id        : pa.typing.Series[int]
    inat_name       : pa.typing.Series[str]
    est_id          : pa.typing.Series[int]
    parent_egt_id   : pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)
    genus_egt_id    : pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"


class TrackingRelSchema(MappingsSchema):
    """
    A rel table that associates tracking list taxa with iNaturalist taxa. Adds check constraint
    asserting that only one of est_id, parent_egt_id, and genus_egt_id are populated.
    """
    est_id: pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)

    @pa.dataframe_check
    def check_exactly_one(cls, df: pd.DataFrame) -> pd.Series:
        """Checks that exactly one of est_id, parent_egt_id, and genus_egt_id are populated."""
        return df[["est_id", "parent_egt_id", "genus_egt_id"]].notna().sum(axis=1) == 1

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"


# ---------------------------------------------------------------------------
# iNaturalist Taxa
# ---------------------------------------------------------------------------

#### Schemas ####
class INatTaxaSchema(pa.DataFrameModel):
    """
    Bare-bones iNaturalist taxon schema needed to search for observations.
    """
    taxon_id        : pa.typing.Series[int] = pa.Field(coerce=True)
    date_updated    : pa.typing.Series[pa.DateTime] = pa.Field(nullable=True, coerce=True)
    match_type      : pa.typing.Series[str] = pa.Field(
        isin=MATCH_TYPES
    )

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"


    #### Check Types ####
    @pa.check_types
    @staticmethod
    def filter_match_type(df: pd.DataFrame, match_types: list = None) -> DataFrame[INatTaxaSchema]:
        """
        Filter out taxa that whose match_type is not in the match_types list argument. Default
        match_type values to keep are "exact" and "override".
        """
        if not match_types:
            match_types = ["exact", "override"]

        return df[df["match_type"].isin(match_types)]


    @pa.check_types
    @staticmethod
    def apply_date_filter(df: pd.DataFrame, days: int, today: dt.date) -> DataFrame[INatTaxaSchema]: 
        """
        Filters the dataframe for taxa that were last updated more than `days` ago. If
        `days` is zero or None, set all taxa's date_updated column to None. Returns a modified copy.
        """
        filtered_df = df.copy()
        
        # If days is zero, disregard date filter
        if not days:
            filtered_df["date_updated"] = None
            return filtered_df
            # TODO test without overriding date_updated

        # Filter for taxa queried more than days_updated before now
        target_date = today - dt.timedelta(days=days)
        date_mask = pd.to_datetime(filtered_df["date_updated"]) <= pd.Timestamp(target_date)
        filtered_df = filtered_df[(filtered_df["date_updated"].isna()) | date_mask]

        return filtered_df


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

#### Schemas ####
class ObservationSchema(pa.DataFrameModel):
    """
    The schema for an observation from iNaturalist. Includes methods for converting from the raw 
    API response, and converting to and from the sqlite database format.
    """
    observation_id              : pa.typing.Series[int] = pa.Field(unique=True, ge=0)
    uuid                        : pa.typing.Series[str] = pa.Field(unique=True)
    observer_id                 : pa.typing.Series[int] = pa.Field(ge=0)
    taxon_id                    : pa.typing.Series[int] = pa.Field(ge=0)
    license                     : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    latitude                    : pa.typing.Series[float]
    longitude                   : pa.typing.Series[float]
    latitude_private            : pa.typing.Series[float] = pa.Field(nullable=True, coerce=True)
    longitude_private           : pa.typing.Series[float] = pa.Field(nullable=True, coerce=True)
    coordinate_precision        : pa.typing.Series[int] = pa.Field(nullable=True, ge=0, coerce=True)
    coordinate_precision_public : pa.typing.Series[int] = pa.Field(nullable=True, ge=0, coerce=True)
    observed_on_string          : pa.typing.Series[str]
    quality_grade               : pa.typing.Series[str]
    url                         : pa.typing.Series[str]
    description                 : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    id_agreements               : pa.typing.Series[int]
    id_disagreements            : pa.typing.Series[int]
    captive_cultivated          : pa.typing.Series[bool] = pa.Field(coerce=True)
    place_guess                 : pa.typing.Series[str]
    place_guess_private         : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    obscured                    : pa.typing.Series[bool] = pa.Field(coerce=True)
    has_photo                   : pa.typing.Series[bool] = pa.Field(coerce=True)
    has_recording               : pa.typing.Series[bool] = pa.Field(coerce=True)
    observed_on                 : pa.typing.Series[pa.DateTime]
    created_at                  : pa.typing.Series[pa.DateTime]
    updated_at                  : pa.typing.Series[pa.DateTime]

    # Overrides interferance from BaseObservationSchema coersion
    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        coerce = False

    @classmethod
    def from_raw(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert a raw observation dataframe from the API into this schema by converting
        string timestamps to datetimes, then validating the dataframe against this schema.

        Args:
            df: Dataframe of raw observations from the <code>observations</code> module.
        
        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        df = _str_to_datetime(df, ["observed_on", "created_at", "updated_at"])
        return cls.validate(df)

    @classmethod
    def to_sqlite(cls, df: DataFrame[ObservationSchema]) -> pd.DataFrame:
        """
        Converts a dataframe that follows the schema to the simplified format expected by a sqlite 
        database by putting the datetimes in a standardized string format.

        Args:
            df: An observations dataframe that conforms to this schema.
        
        Returns:
            A copy of the dataframe with sqlite-friendly date fields.
        """
        df = df.copy()
        for col in ["observed_on", "created_at", "updated_at"]:
            df[col] = df[col].dt.strftime(DATE_FORMAT)

        return df

    @classmethod
    def from_sqlite(cls, df: pd.DataFrame) -> DataFrame[ObservationSchema]:
        """
        Converts a dataframe that has just come from a sqlite database into one that follows the
        schema by converting string timestamps into datetime64[ns] and validating the dataframe
        against this schema.

        Args:
            df: An observations dataframe that has sqlite datatypes.

        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        for col in ["observed_on", "created_at", "updated_at"]:
            df[col] = pd.to_datetime(df[col], format=DATE_FORMAT)

        return cls.validate(df)


class FullObservationSchema(ObservationSchema, TrackingListSchema):
    """
    This model defines what the cleaned version of the full observations dataset should look like
    after being extracted from the database. Both the tracking taxa columns and the observation 
    columns are in the clean format.
    """
    est_id          : pa.typing.Series[int] = pa.Field(unique=False, ge=0)
    egt_id          : pa.typing.Series[int] = pa.Field(unique=False, ge=0)
    observation_id  : pa.typing.Series[int] = pa.Field(unique=False, ge=0)
    uuid            : pa.typing.Series[str] = pa.Field(unique=False)
    # TODO change to unqiue=True and test
    name            : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    login           : pa.typing.Series[str]


# ---------------------------------------------------------------------------
# Identifications
# ---------------------------------------------------------------------------

#### Schema ####
class IdentificationsSchema(pa.DataFrameModel):
    """
    This model defines what an identification coming from the iNaturalist API should look like.

    This class provides methods for converting from the raw dataframe to the schema, from the 
    schema to a sqlite format, and from the sqlite format back to the schema.
    """
    observation_id      : pa.typing.Series[int] = pa.Field(ge=0)
    user_id             : pa.typing.Series[int] = pa.Field(ge=0)
    identification_id   : pa.typing.Series[int] = pa.Field(unique=True, ge=0)
    created_at          : pa.typing.Series[pa.DateTime]
    taxon_id            : pa.typing.Series[int]

    @classmethod
    def from_raw(
        cls,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Convert a raw identifications dataframe from the API into this schema by converting
        string timestamps with timezones to naive localized datetimes, then validating the 
        dataframe against this schema.

        Args:
            df: Dataframe of raw identifications from the <code>observations</code> module.
            tz: Timezone to convert datetimes to before localizing them.
        
        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        df = _str_to_datetime(df, ["created_at"])
        return cls.validate(df)


    @classmethod
    def to_sqlite(
        cls,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Converts a dataframe that follows this schema to the simplified format expected by a sqlite 
        database by putting the datetimes in a standardized string format.

        Args:
            df: An identifications dataframe that conforms to this schema.
        
        Returns:
            A copy of the dataframe with sqlite-friendly date fields.
        """
        df = df.copy()
        df["created_at"] = df["created_at"].dt.strftime(DATE_FORMAT)
        return df


    @classmethod
    def from_sqlite(
        cls,
        df: pd.DataFrame
    ):
        """
        Converts a dataframe that has just come from a sqlite database into one that follows the
        schema by converting string timestamps into datetime64[ns] and validating the dataframe
        against this schema.

        Args:
            df: An identifications dataframe that has sqlite datatypes.

        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        if not "created_at" in df.columns:
            raise ValueError("Observations dataframe does not contain expected column: created_at")
        df["created_at"] = pd.to_datetime(df["created_at"], format=DATE_FORMAT)
        return df


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

#### Schema ####
class UsersSchema(pa.DataFrameModel):
    """
    This model defines the data for an iNaturalist user.

    This schema provides a method for converting from the raw dataframe to the schema, but it's
    not necessary to convert between the schema and a sqlite format.
    """
    user_id     : pa.typing.Series[int] = pa.Field(ge=0, unique=True)
    login       : pa.typing.Series[str]
    name        : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)

    @classmethod
    def from_raw(
        cls,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Convert a raw users dataframe from the API into this schema by changing the name of the id
        column to user_id.

        Args:
            df: Dataframe of raw users from the <code>observations</code> module.
        
        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        if (not "user_id" in df.columns) and ("id" in df.columns):
            df = df.rename(columns={"id": "user_id"})

        return cls.validate(df)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

#### Schema ####
class AnnotationsSchema(pa.DataFrameModel):
    """
    This model defines the data for an annotation left on an observation.

    It includes the observation ID, the annotation category ID, the annotation value ID, and the
    ID of the user who left the annotation, along with the annotation's vote score.
    """
    observation_id  : pa.typing.Series[int]
    annotation_id   : pa.typing.Series[int]
    value_id        : pa.typing.Series[int]
    user_id         : pa.typing.Series[int]
    vote_score      : pa.typing.Series[int]


# ---------------------------------------------------------------------------
# Experts
# ---------------------------------------------------------------------------

#### Schema ####
class ExpertsSchema(pa.DataFrameModel):
    """
    This model defines a schema for the experts list.

    This class provides methods for converting a raw dataframe from the csv import to the schema.
    """
    user_id     : pa.typing.Series[int] = pa.Field(unique=True, coerce=True)
    expertise   : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"

    @classmethod
    def from_raw(
        cls, 
        df: pd.DataFrame, 
        id_field: str, 
        expertise_field: str
    ):
        """
        Convert a raw experts CSV into this schema.

        Args:
            df: Raw experts dataframe.
            id_field: Name of column in `df` holding the iNaturalist user ID.
            expertise_field: Name of column in `df` holding the expertise value.
        """
        df = df.copy()

        missing = [col for col in (id_field, expertise_field) if col not in df.columns]
        if missing:
            raise ValueError(
                f"Experts CSV is missing expected column(s): {missing}. "
                f"Available columns: {list(df.columns)}"
            )
        
        renames = {
            id_field        : "user_id",
            expertise_field : "expertise",
        }

        df = df.rename(columns=renames)
        df = df.dropna(how="all")
        return cls.validate(df)


# ---------------------------------------------------------------------------
# ExpertIDs
# ---------------------------------------------------------------------------

#### Schema ####
class ExpertIDsSchema(IdentificationsSchema, UsersSchema, ExpertsSchema):
    """
    This model defines a schema for a list of identifications made by experts. It combines fields 
    from the identifications, users, and experts schema. 

    Calling from_sqlite will invoke IdentificationSchema's method to convert the string timestamps 
    to datetime64[ns].

    Calling from_raw should not be necessary: expert identifications are a construct of a database 
    join between experts, tracked taxa, and identifications and thus have no raw data source.
    """
    user_id : pa.typing.Series[int] = pa.Field(unique=False)
    est_id  : pa.typing.Series[int]
    elcode  : pa.typing.Series[str]

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = False
        coerce = False


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

#### Schema ####
class ExportSchema(pa.DataFrameModel):
    """
    This model defines what the final data export will be. It uses the column names prescribed by
    the Observations.gdb format used by ORBIC. This is subject to change in the future.
    """
    catalogNumber       : pa.typing.Series[int]     # observation_id
    UniqueSurveyID      : pa.typing.Series[str]     # uuid
    v_date              : pa.typing.Series[pa.DateTime]     # observed_on
    visit_date          : pa.typing.Series[str]     # observed_on_string
    v_by                : pa.typing.Series[str]     # name
    v_note              : pa.typing.Series[str]     # description
    directions          : pa.typing.Series[str]     # place_guess
    latitude            : pa.typing.Series[float]   # latitude
    longitude           : pa.typing.Series[float]   # longitude
    DISTANCE            : pa.typing.Series[int] = (
        pa.Field(nullable=True, coerce=True)        # coordinate_precision
    )
    sci_name            : pa.typing.Series[str]
    search_type         : pa.typing.Series[str]     # "Element"
    Dataset             : pa.typing.Series[str]     # "iNaturalist"
    dist_unit           : pa.typing.Series[str]     # "Meters"
    sf_type             : pa.typing.Series[str]     # "point"
    est_id              : pa.typing.Series[int]
    element_type_species: pa.typing.Series[str]     # Same as element_type
    element_type        : pa.typing.Series[str]
    scientific_name     : pa.typing.Series[str]
    common_name         : pa.typing.Series[str]
    element_name        : pa.typing.Series[str]
    family              : pa.typing.Series[str]
    author              : pa.typing.Series[str]
    egt_uid             : pa.typing.Series[str]
    srank               : pa.typing.Series[str]
    track_status        : pa.typing.Series[str]
    explorer            : pa.typing.Series[str]
    explorer_link       : pa.typing.Series[str]
    elcode              : pa.typing.Series[str]
    growth_habit        : pa.typing.Series[str]
    duration            : pa.typing.Series[str]
    date_option         : pa.typing.Series[str]     # "exact"
    detected_ind        : pa.typing.Series[str]     # "Y"
    ownerInstitutionCode: pa.typing.Series[str]     # "iNaturalist"
    dateIdentified      : pa.typing.Series[pa.DateTime] = pa.Field(nullable=True, coerce=True)
    identifiedBy        : pa.typing.Series[str]
    identificationReferences: pa.typing.Series[str]
    evidence_type       : pa.typing.Series[str]
    # Additional columns
    url                 : pa.typing.Series[str]
    obscured            : pa.typing.Series[bool]
    license             : pa.typing.Series[str]
    project_license     : pa.typing.Series[str]
    permission_to_use   : pa.typing.Series[bool]
    annotations         : pa.typing.Series[str]
    expert_verified     : pa.typing.Series[str]

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"
