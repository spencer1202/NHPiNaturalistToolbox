"""
This module contains dataframe models that validate the data coming into and out of the pipeline.

This includes cleaning raw data coming from .csv files and the iNaturalist API, and converting to 
and from the data types expected by a sqlite database.
"""
#### Standard Imports ####
import logging
from typing import Optional

#### Third-party imports ####
import numpy as np
import pandas as pd
import pandera.pandas as pa
import pandera.typing

#### Constants ####
# String format for storing datetimes in sqlite
DATE_FORMAT = "%Y-%m-%d"

# Experts list default fields
# TODO do this for tracking list
EXPERTS_INAT_ID_FIELD = "iNaturalist_id"
EXPERTS_EXPERTISE_FIELD = "Expertise LU"

#### Setup ####
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
class TrackingSchemaRaw(pa.DataFrameModel):
    """Format of raw tracking list from CSV file."""
    name                : int = pa.Field(ge=0)
    sname               : str
    author              : str = pa.Field(nullable=True, coerce=True)
    scomname            : str = pa.Field(nullable=True, coerce=True)
    s_rank              : str
    eo_track_status_desc: str
    explorer            : str
    egt_uid             : str
    family              : str
    ELCODE_BCD          : str
    NAME_CATEGORY_DESC  : str
    growth_habit        : str = pa.Field(nullable=True, coerce=True)
    element_type        : str = pa.Field(nullable=True, coerce=True)
    duration            : str = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"      # remove extra columns


class TrackingSchemaClean(pa.DataFrameModel):
    """Tracking list with added and renamed columns."""
    # Element subnational tracking ID
    est_id          : int = pa.Field(unique=True, ge=0)
    # Scientific name
    sci_name        : str
    # Name searched for
    search_name     : Optional[str]
    # Whether the taxa is described
    is_described    : Optional[bool] = pa.Field(coerce=True)
    # Category (e.g. plant, animal, fungi)
    element_type    : str = pa.Field(nullable=True, coerce=True)
    # Scientific name italicized with <i></i>
    scientific_name : str
    # Common name
    common_name     : str = pa.Field(nullable=True, coerce=True)
    # EST ID as a string
    element_name    : str
    # Taxon's family name
    family          : str
    # Taxon author
    author          : str = pa.Field(nullable=True, coerce=True)
    # Internal Biotics tracking ID
    egt_uid         : str
    # Subnational rank
    srank           : str
    # Tracking status
    track_status    : str
    # Link to Oregon explorer entry
    explorer        : str
    # Explorer entry formatted as HTML ref tag
    explorer_link   : str
    # ELCODE
    elcode          : str
    # For plants/fungi (herbaceous, moss, fungus)
    growth_habit    : str = pa.Field(nullable=True, coerce=True)
    # For plants/fungi (perenial, annual)
    duration        : str = pa.Field(nullable=True, coerce=True)

    @classmethod
    def from_raw(
        cls,
        df: pandera.typing.DataFrame[TrackingSchemaRaw]
    ) -> pandera.typing.DataFrame['TrackingSchemaClean']:
        """
        Converts a raw tracking list dataframe to the clean schema and validates it.
        
        Renames columns, adds derived columns element_name, explorer_link, and scientific_name, 
        replaces empty strings with NaN, and validates the dataframe against the 
        schema.
        """
        renames = {
            "name"                  : "est_id",
            "sname"                 : "sci_name",
            "element_type"          : "element_type",
            "scomname"              : "common_name",
            "family"                : "family",
            "author"                : "author",
            "egt_uid"               : "egt_uid",
            "s_rank"                : "srank",
            "eo_track_status_desc"  : "track_status",
            "explorer"              : "explorer", 
            "ELCODE_BCD"            : "elcode",
            "growth_habit"          : "growth_habit",
            "duration"              : "duration"
        }

        clean_df = df.rename(columns=renames)

        clean_df["element_name"] = clean_df["est_id"].astype(str)   # add element name column
        clean_df = clean_df.drop_duplicates(subset="est_id")        # drop duplicate est_ids

        clean_df["explorer_link"] = (
            clean_df["explorer"]
            .apply(lambda x: f"<a href=\"{x}\">View in Explorer</a>")
        )
        clean_df["scientific_name"] = (
            clean_df["sci_name"]
            .apply(lambda x: f"<i>{x}</i>")
        )

        clean_df = clean_df.replace(r"^\s*$", np.nan, regex=True)   # replace empty strings with NaN

        return cls.validate(clean_df)


# ---------------------------------------------------------------------------
# iNaturalist Taxa
# ---------------------------------------------------------------------------
class TaxonMappingSchema(pa.DataFrameModel):
    """
    Schema for a table that maps tracking taxa to iNaturalist taxa retrieved from the iNaturalist
    taxa API.
    """
    est_id          : pa.typing.Series[int]
    taxon_id        : pa.typing.Series[int]
    inat_name       : pa.typing.Series[str]

# ---------------------------------------------------------------------------
# Alternative names
# ---------------------------------------------------------------------------
class AlternativeNamesSchema(pa.DataFrameModel):
    """
    Alternative taxon names retrieved from the iNaturalist taxa API.
    """
    taxon_id                : pa.typing.Series[int]
    alternative_taxon_id    : pa.typing.Series[int]
    alternative_inat_name   : pa.typing.Series[str]


# ---------------------------------------------------------------------------
# Name overrides list
# ---------------------------------------------------------------------------

class OverridesSchema(pa.DataFrameModel):
    """Manual overrides for tracking list taxon names."""
    est_id      : pa.typing.Series[int]
    inat_name	: pa.typing.Series[str]
    taxon_id    : pa.typing.Series[int] = pa.Field(nullable=True, coerce=True)

    # pylint: disable=too-few-public-methods
    # pylint: disable=missing-class-docstring
    class Config:
        strict = "filter"


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------
def str_to_datetime(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """
    Helper function that converts the given date columns to a naive pa.DateTime.
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

# Formats that dates come in
# 2016-11-15T00:30:31-08:00
# 2026-06-11 15:04
# 2026-06-11

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
        string timestamps with timezones to naive localized datetimes, then validating the 
        dataframe against this schema.

        Args:
            df: Dataframe of raw observations from the <code>observations</code> module.
            tz: Timezone to convert datetimes to before localizing them.
        
        Returns:
            A validated copy of the dataframe that conforms to this schema.
        """
        df = df.copy()
        df = str_to_datetime(df, ["observed_on", "created_at", "updated_at"])
        return cls.validate(df)

    @classmethod
    def to_sqlite(cls, df: pandera.typing.DataFrame['ObservationSchema']) -> pd.DataFrame:
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
    def from_sqlite(cls, df: pd.DataFrame) -> pd.DataFrame:
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


class FullObservationSchema(ObservationSchema, TrackingSchemaClean):
    """
    This model defines what the cleaned version of the full observations dataset should look like
    after being extracted from the database. Both the tracking taxa columns and the observation 
    columns are in the clean format.
    """
    est_id          : pa.typing.Series[int] = pa.Field(unique=False, ge=0)
    observation_id  : pa.typing.Series[int] = pa.Field(unique=False, ge=0)
    uuid            : pa.typing.Series[str] = pa.Field(unique=False)
    # TODO change to unqiue=True and test
    name            : pa.typing.Series[str] = pa.Field(nullable=True, coerce=True)
    login           : pa.typing.Series[str]




# ---------------------------------------------------------------------------
# Identifications
# ---------------------------------------------------------------------------
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
        df = str_to_datetime(df, ["created_at"])
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
        id_field: str = EXPERTS_INAT_ID_FIELD, 
        expertise_field: str = EXPERTS_EXPERTISE_FIELD
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
# ExpertIDs
# ---------------------------------------------------------------------------
class ExportSchema(pa.DataFrameModel):
    """
    This model defines what the final data export will be. It uses the column names prescribed by
    the Observations.gdb format used by ORBIC. This is subject to change in the future.
    """
    catalogNumber       : pa.typing.Series[int]     # observation_id
    UniqueSurveyID      : pa.typing.Series[str]     # uuid
    v_date              : pa.typing.Series[str]     # observed_on w/o timestame
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
