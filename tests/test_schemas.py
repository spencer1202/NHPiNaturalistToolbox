import pickle as pkl
import pytest
import pandas as pd
import pandas.api.types as ptypes
import pandera as pa

from inatdatapipeline.schemas.validation import (
    ObservationSchema,
    FullObservationSchema,
    IdentificationsSchema,
    UsersSchema,
    ExpertsSchema,
    ExpertIDsSchema,
    str_to_datetime,
)
from inatdatapipeline.client.observations import ObservationResults


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# check_dates
# ---------------------------------------------------------------------------

class TestCheckDates:
    def test_converts_to_datetime(self):
        df = pd.DataFrame({"date": ["2024-03-15"]})
        result = str_to_datetime(df, ["date"])
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_strips_timezone(self):
        df = pd.DataFrame({"date": ["2024-03-15T00:00:00+00:00"]})
        result = str_to_datetime(df, ["date"])
        assert result["date"].dt.tz is None


    def test_raises_on_missing_column(self):
        df = pd.DataFrame({"other_col": ["value"]})
        with pytest.raises(ValueError, match="does not contain expected column"):
            str_to_datetime(df, ["date"])

    def test_multiple_columns(self):
        df = pd.DataFrame({
            "created_at": ["2024-03-16T10:00:00+00:00"],
            "updated_at": ["2024-03-17T10:00:00+00:00"],
        })
        result = str_to_datetime(df, ["created_at", "updated_at"])
        assert pd.api.types.is_datetime64_any_dtype(result["created_at"])
        assert pd.api.types.is_datetime64_any_dtype(result["updated_at"])

    def test_coerces_invalid_dates_to_nat(self):
        df = pd.DataFrame({"date": ["not-a-date"]})
        result = str_to_datetime(df, ["date"])
        assert pd.isna(result["date"].iloc[0])


# ---------------------------------------------------------------------------
# TrackingSchemaRaw
# ---------------------------------------------------------------------------
# TODO add tests

# ---------------------------------------------------------------------------
# TrackingSchemaClean
# ---------------------------------------------------------------------------
# TODO add tests


# ---------------------------------------------------------------------------
# ObservationSchema.from_raw
# ---------------------------------------------------------------------------

class TestObservationSchemaFromRaw:
    def test_valid_df_passes(self, raw_observation_df):
        result = ObservationSchema.from_raw(raw_observation_df)
        assert result is not None

    def test_date_columns_are_datetime(self, clean_observation_df):
        for col in ["observed_on", "created_at", "updated_at"]:
            assert pd.api.types.is_datetime64_any_dtype(clean_observation_df[col])

    def test_date_columns_are_timezone_naive(self, clean_observation_df):
        for col in ["observed_on", "created_at", "updated_at"]:
            assert clean_observation_df[col].dt.tz is None

    def test_observation_id_is_unique(self, raw_observation_df):
        raw_observation_df["observation_id"] = [1, 1]
        with pytest.raises(pa.errors.SchemaError):
            ObservationSchema.from_raw(raw_observation_df)

    def test_negative_observation_id_fails(self, raw_observation_df):
        raw_observation_df["observation_id"] = [-1, 2]
        with pytest.raises(pa.errors.SchemaError):
            ObservationSchema.from_raw(raw_observation_df)

    def test_nullable_columns_accept_none(self, raw_observation_df):
        raw_observation_df["license"] = None
        raw_observation_df["description"] = None
        result = ObservationSchema.from_raw(raw_observation_df)
        assert result is not None

    def test_coordinate_precision_coerced_from_float(self, raw_observation_df):
        raw_observation_df["coordinate_precision"] = [10.0, None]
        result = ObservationSchema.from_raw(raw_observation_df)
        assert result is not None

    def test_bool_columns_coerced(self, raw_observation_df):
        raw_observation_df["captive_cultivated"] = [1, 0]
        raw_observation_df["obscured"] = [0, 1]
        result = ObservationSchema.from_raw(raw_observation_df)
        assert result["captive_cultivated"].dtype == bool

    def test_does_not_mutate_input(self, raw_observation_df):
        original = raw_observation_df["created_at"].copy()
        ObservationSchema.from_raw(raw_observation_df)
        pd.testing.assert_series_equal(raw_observation_df["created_at"], original)


# ---------------------------------------------------------------------------
# ObservationSchema.to_sqlite
# ---------------------------------------------------------------------------

class TestObservationSchemaToSqlite:
    def test_date_columns_converted_to_strings(self, clean_observation_df):
        result = ObservationSchema.to_sqlite(clean_observation_df)
        assert ptypes.is_string_dtype(result["observed_on"].dtype)
        assert ptypes.is_string_dtype(result["created_at"].dtype)
        assert ptypes.is_string_dtype(result["updated_at"].dtype)

    def test_observed_on_format(self, clean_observation_df):
        result = ObservationSchema.to_sqlite(clean_observation_df)
        # Should be YYYY-MM-DD
        pd.to_datetime(result["observed_on"], format="%Y-%m-%d")

    def test_created_at_format(self, clean_observation_df):
        result = ObservationSchema.to_sqlite(clean_observation_df)
        # Should be YYYY-MM-DD
        pd.to_datetime(result["created_at"], format="%Y-%m-%d")

    def test_updated_at_format(self, clean_observation_df):
        result = ObservationSchema.to_sqlite(clean_observation_df)
        pd.to_datetime(result["updated_at"], format="%Y-%m-%d")

    def test_does_not_mutate_input(self, clean_observation_df):
        original_dtype = clean_observation_df["created_at"].dtype
        ObservationSchema.to_sqlite(clean_observation_df)
        assert clean_observation_df["created_at"].dtype == original_dtype

    def test_roundtrip(self, raw_observation_df):
        """Data converted to sqlite format and back should preserve date values."""
        clean = ObservationSchema.from_raw(raw_observation_df)
        sqlite_ready = ObservationSchema.to_sqlite(clean)
        restored = ObservationSchema.from_raw(sqlite_ready)
        pd.testing.assert_series_equal(
            clean["observed_on"].dt.date.reset_index(drop=True),
            restored["observed_on"].dt.date.reset_index(drop=True),
        )


# ---------------------------------------------------------------------------
# IdentificationsSchema.from_raw
# ---------------------------------------------------------------------------

class TestIdentificationsSchema:
    def test_valid_df_passes(self, raw_identifications_df):
        result = IdentificationsSchema.from_raw(raw_identifications_df)
        assert result is not None

    def test_created_at_is_datetime(self, raw_identifications_df):
        result = IdentificationsSchema.from_raw(raw_identifications_df)
        assert pd.api.types.is_datetime64_any_dtype(result["created_at"])

    def test_created_at_is_timezone_naive(self, raw_identifications_df):
        result = IdentificationsSchema.from_raw(raw_identifications_df)
        assert result["created_at"].dt.tz is None

    def test_identification_id_is_unique(self, raw_identifications_df):
        raw_identifications_df["identification_id"] = [501, 501, 503]
        with pytest.raises(pa.errors.SchemaError):
            IdentificationsSchema.from_raw(raw_identifications_df)

    # Removed 'current' field
    # def test_current_coerced_from_int(self, raw_identifications_df):
    #     raw_identifications_df["current"] = [1, 0, 1]
    #     result = IdentificationsSchema.from_raw(raw_identifications_df)
    #     assert result["current"].dtype == bool

    def test_negative_user_id_fails(self, raw_identifications_df):
        raw_identifications_df["user_id"] = [-1, 11, 12]
        with pytest.raises(pa.errors.SchemaError):
            IdentificationsSchema.from_raw(raw_identifications_df)

    def test_does_not_mutate_input(self, raw_identifications_df):
        original = raw_identifications_df["created_at"].copy()
        IdentificationsSchema.from_raw(raw_identifications_df)
        pd.testing.assert_series_equal(raw_identifications_df["created_at"], original)


class TestIdentificationSchemaToSqlite:
    def test_created_at_is_string(self, clean_identifications_df):
        result = IdentificationsSchema.to_sqlite(clean_identifications_df)
        assert pd.api.types.is_string_dtype(result["created_at"])
        assert clean_identifications_df.loc[0, "created_at"], pd.to_datetime(result.loc[0, "created_at"], format="%Y-%m-%d %H:%M:%S")
        assert clean_identifications_df.loc[1, "created_at"], pd.to_datetime(result.loc[1, "created_at"], format="%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------------
# UsersSchema
# ---------------------------------------------------------------------------

class TestUsersSchema:
    def test_valid_df_passes(self, users_df):
        result = UsersSchema.validate(users_df)
        assert result is not None

    def test_user_id_is_unique(self, users_df):
        users_df["user_id"] = [1, 1, 3]
        with pytest.raises(pa.errors.SchemaError):
            UsersSchema.validate(users_df)

    def test_negative_user_id_fails(self, users_df):
        users_df["user_id"] = [-1, 2, 3]
        with pytest.raises(pa.errors.SchemaError):
            UsersSchema.validate(users_df)

    def test_nullable_name_accepted(self, users_df):
        users_df["name"] = None
        result = UsersSchema.validate(users_df)
        assert result is not None

    def test_name_coerced_from_non_string(self, users_df):
        users_df["name"] = [1, 2, 3]
        result = UsersSchema.validate(users_df)
        assert ptypes.is_string_dtype(result["name"].dtype)


# ---------------------------------------------------------------------------
# ExpertsSchema
# ---------------------------------------------------------------------------
class TestExpertsSchema:
    def test_valid_df_passes_from_raw(self, experts_raw):
        result = ExpertsSchema.from_raw(experts_raw)
        assert result is not None
        for col in ["user_id", "expertise"]:
            assert col in result.columns
        
    def test_missing_field_raises(self, experts_raw):
        experts_missing = experts_raw.drop(columns=["iNaturalist_id"])
        with pytest.raises(pa.errors.SchemaError):
            result = ExpertsSchema.from_raw(experts_missing)


# ---------------------------------------------------------------------------
# FullObservationsSchema
# ---------------------------------------------------------------------------
class TestFullObservationsSchema:
    def test_est_id_not_unique(self, full_observation_from_sqlite_df):
        full_observation_from_sqlite_df["est_id"] = [1, 1]
        result = FullObservationSchema.from_sqlite(full_observation_from_sqlite_df)
        assert result is not None
    
    def test_observation_id_not_unique(self, full_observation_from_sqlite_df):
        full_observation_from_sqlite_df["observation_id"] = [1, 1]
        result = FullObservationSchema.from_sqlite(full_observation_from_sqlite_df)
        assert result is not None
    
    def test_booleans_convert_correctly(self, full_observation_from_sqlite_df):
        result = FullObservationSchema.from_sqlite(full_observation_from_sqlite_df)
        for col in ["obscured", "has_photo", "has_recording"]:
            assert pd.api.types.is_bool_dtype(result[col].dtype)
    
    def test_datetimes_convert_correctly(self, full_observation_from_sqlite_df):
        result = FullObservationSchema.from_sqlite(full_observation_from_sqlite_df)
        for col in ["observed_on", "created_at", "updated_at"]:
            assert pd.api.types.is_datetime64_dtype(result[col].dtype)


# ---------------------------------------------------------------------------
# ExpertIDsSchema
# ---------------------------------------------------------------------------
class TestExpertIDsSchema:
    def test_user_id_not_unique(self, expert_ids):
        result = ExpertIDsSchema.from_raw(expert_ids)
        assert result is not None
    
    def test_doesnt_filter_columns(self, expert_ids):
        expert_ids["extra_column"] = ["A", "B", "C", "D"]
        result = ExpertIDsSchema.from_raw(expert_ids)
        assert result["extra_column"] is not None
    
    def test_identification_id_is_unique(self, expert_ids):
        result = ExpertIDsSchema.from_raw(expert_ids)
        assert len(result["identification_id"].unique()) == len(result["identification_id"])
    
    def test_has_correct_column_dtypes(self, expert_ids):
        result = ExpertIDsSchema.from_raw(expert_ids)
        cols = {
            "observation_id"    : pd.api.types.is_integer_dtype,
            "user_id"           : pd.api.types.is_integer_dtype,
            "identification_id" : pd.api.types.is_integer_dtype,
            "created_at"        : pd.api.types.is_datetime64_dtype,
            "taxon_id"          : pd.api.types.is_integer_dtype,
            "login"             : pd.api.types.is_string_dtype,
            "name"              : pd.api.types.is_string_dtype,
            "expertise"         : pd.api.types.is_string_dtype
        }
        for col, func in cols.items():
            assert func(result[col].dtype)