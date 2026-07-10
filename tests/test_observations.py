"""
Tests for inatdatapipeline/client/observations.py
"""
import datetime as dt
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from inatdatapipeline.client.observations import (
    ObservationResults,
    _get_batches,
    _create_date_taxon_map,
    _apply_date_filter,
    _unpack_observation,
    _unpack_identifications,
    _unpack_annotations,
    _unpack_results,
    fetch_observations,
)
from inatdatapipeline.schemas.config import ObservationsConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth():
    mock = MagicMock()
    mock.get_auth_headers.return_value = {"Authorization": "Bearer test_token"}
    return mock

@pytest.fixture
def config():
    return ObservationsConfig(
        place_id=10,
        quality_grade="research",
        per_page=200,
        batch_size=30,
        update_after_days=7,
        max_observations=10000,
        project_id=247148,
        fields_json="src/inatdatapipeline/obs_fields.json",
        timezone= "America/Los_Angeles"
    )

@pytest.fixture
def taxa_df():
    return pd.DataFrame({
        "taxon_id":     [1, 2, 3],
        "date_updated": ["2026-01-01", "2026-01-01", None]
    })

@pytest.fixture
def observation_data():
    """A minimal valid iNaturalist observation dict."""
    return {
        "id"                                : 1001,
        "user"                              : {"id": 1, "login": "user1", "name": "Name Nameson"},
        "community_taxon_id"                : 99,
        "license_code"                      : "cc-by",
        "geojson"                           : {"coordinates": [-122.4, 37.8]},
        "private_geojson"                   : {"coordinates": [-122.5234, 37.2339]},
        "positional_accuracy"               : 10,
        "public_positional_accuracy"        : 50,
        "observed_on"                       : "2024-03-15",
        "observed_on_string"                : "March 15, 2024",
        "created_at"                        : "2024-03-16T10:00:00Z",
        "updated_at"                        : "2024-03-17T10:00:00Z",
        "quality_grade"                     : "research",
        "uri"                               : "https://www.inaturalist.org/observations/1001",
        "description"                       : "Found near stream",
        "num_identification_agreements"     : 3,
        "num_identification_disagreements"  : 0,
        "captive"                           : False,
        "place_guess"                       : None,
        "place_guess_private"               : "123 My House",
        "obscured"                          : True,
        "photos"                            : [{"id": 1}],
        "sounds"                            : [],
        "identifications"                   : [],
        "annotations"                       : [],
    }

@pytest.fixture
def identification_data():
    return {
        "id":           501,
        "user":         {"id": 10, "login": "identifier1", "name": "Identifier One"},
        "created_at":   "2024-03-16T12:00:00Z",
        # "current":      True,
        "taxon":        {"id": 99},
    }


def make_observation(obs_id: int, user_id: int = 42) -> dict:
    """Factory for minimal observation dicts with distinct IDs."""
    return {
        "id":                               obs_id,
        "user":                             {"id": user_id, "login": f"user{user_id}"},
        "community_taxon_id":               99,
        "license_code":                     "cc-by",
        "geojson":                          {"coordinates": [-122.4, 37.8]},
        "private_geojson":                  None,
        "positional_accuracy":              10,
        "public_positional_accuracy":       50,
        "observed_on":                      "2024-03-15",
        "observed_on_string":               "March 15, 2024",
        "created_at":                       "2024-03-16T10:00:00Z",
        "updated_at":                       "2024-03-17T10:00:00Z",
        "quality_grade":                    "research",
        "uri":                              f"https://www.inaturalist.org/observations/{obs_id}",
        "description":                      None,
        "num_identification_agreements":    0,
        "num_identification_disagreements": 0,
        "captive":                          False,
        "place_guess":                      "Somewhere",
        "place_guess_private":              None,
        "obscured":                         False,
        "photos":                           [],
        "sounds":                           [],
        "identifications":                  [],
        "annotations":                      [],
    }

@pytest.fixture
def observation_results_raw(raw_observation_df, raw_identifications_df, users_df, annotations_df):
    obs_raw = ObservationResults()
    obs_raw.observations    = raw_observation_df.to_dict(orient="records")
    obs_raw.identifications = raw_identifications_df.to_dict(orient="records")
    obs_raw.users           = users_df.to_dict(orient="records")
    obs_raw.annotations     = annotations_df.to_dict(orient="records")
    obs_raw.completed_taxa  = set(raw_observation_df["taxon_id"].unique())

    return obs_raw

# ---------------------------------------------------------------------------
# _get_batches
# ---------------------------------------------------------------------------

class TestGetBatches:
    def test_splits_evenly(self):
        result = list(_get_batches([1, 2, 3, 4], 2))
        assert result == [[1, 2], [3, 4]]

    def test_handles_remainder(self):
        result = list(_get_batches([1, 2, 3], 2))
        assert result == [[1, 2], [3]]

    def test_single_batch(self):
        result = list(_get_batches([1, 2, 3], 10))
        assert result == [[1, 2, 3]]

    def test_empty_list(self):
        result = list(_get_batches([], 5))
        assert result == []

    def test_batch_size_one(self):
        result = list(_get_batches([1, 2, 3], 1))
        assert result == [[1], [2], [3]]


# ---------------------------------------------------------------------------
# _create_date_taxon_map
# ---------------------------------------------------------------------------

class TestCreateDateTaxonMap:
    def test_groups_by_date(self):
        df = pd.DataFrame({
            "taxon_id":     [1, 2, 3],
            "date_updated": ["2024-01-01", "2024-01-01", "2024-02-01"],
        })
        result = _create_date_taxon_map(df)
        assert result["2024-01-01"] == {1, 2}
        assert result["2024-02-01"] == {3}

    def test_null_dates_grouped_under_none_key(self):
        df = pd.DataFrame({
            "taxon_id":     [1, 2],
            "date_updated": [None, "2024-01-01"],
        })
        result = _create_date_taxon_map(df)
        assert 1 in result["None"]

    def test_all_null_dates(self):
        df = pd.DataFrame({
            "taxon_id":     [1, 2],
            "date_updated": [None, None],
        })
        result = _create_date_taxon_map(df)
        assert result["None"] == {1, 2}

    def test_no_null_dates_none_key_is_empty(self):
        df = pd.DataFrame({
            "taxon_id":     [1, 2],
            "date_updated": ["2024-01-01", "2024-02-01"],
        })
        result = _create_date_taxon_map(df)
        assert result["None"] == set()


# ---------------------------------------------------------------------------
# _apply_date_filter
# ---------------------------------------------------------------------------

class TestApplyDateFilter:
    def test_none_update_days_clears_dates(self, taxa_df):
        result = _apply_date_filter(taxa_df.copy(), None)
        assert result["date_updated"].isna().all()

    def test_zero_update_days_clears_dates(self, taxa_df):
        result = _apply_date_filter(taxa_df.copy(), 0)
        assert result["date_updated"].isna().all()

    def test_does_not_mutate_input(self, taxa_df):
        original_dates = taxa_df["date_updated"].copy()
        _apply_date_filter(taxa_df, None)
        pd.testing.assert_series_equal(taxa_df["date_updated"], original_dates)

    def test_filters_recently_updated_taxa(self):
        df = pd.DataFrame({
            "taxon_id":     [1, 2],
            "date_updated": [
                str(dt.date.today() - dt.timedelta(days=1)),   # updated yesterday, filtered out
                str(dt.date.today() - dt.timedelta(days=30)),  # updated 30 days ago, kept
            ],
        })
        result = _apply_date_filter(df, 7)
        assert 1 not in result["taxon_id"].values
        assert 2 in result["taxon_id"].values

    def test_keeps_null_date_taxa(self):
        df = pd.DataFrame({
            "taxon_id":     [1],
            "date_updated": [None],
        })
        result = _apply_date_filter(df, 7)
        assert len(result) == 1

    def test_keeps_taxa_updated_exactly_on_boundary(self):
        target = dt.date.today() - dt.timedelta(days=7)
        df = pd.DataFrame({
            "taxon_id":     [1],
            "date_updated": [str(target)],
        })
        result = _apply_date_filter(df, 7)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _unpack_observation
# ---------------------------------------------------------------------------

class TestUnpackObservation:
    def test_extracts_basic_fields(self, observation_data):
        result = _unpack_observation(observation_data)
        assert result["observation_id"] == 1001
        assert result["observer_id"] == 1
        assert result["taxon_id"] == 99
        assert result["quality_grade"] == "research"

    def test_geojson_longitude_latitude_order(self, observation_data):
        # GeoJSON is [longitude, latitude]
        result = _unpack_observation(observation_data)
        assert result["longitude"] == -122.4
        assert result["latitude"] == 37.8

    def test_private_geojson_uses_private_field(self, observation_data):
        # Private coords should come from private_geojson, not geojson
        result = _unpack_observation(observation_data)
        assert result["longitude_private"] == -122.5234
        assert result["latitude_private"] == 37.2339

    def test_private_coords_differ_from_public(self, observation_data):
        result = _unpack_observation(observation_data)
        assert result["longitude_private"] != result["longitude"]
        assert result["latitude_private"] != result["latitude"]

    def test_has_photo_true_when_photos_present(self, observation_data):
        result = _unpack_observation(observation_data)
        assert result["has_photo"] is True

    def test_has_photo_false_when_no_photos(self, observation_data):
        observation_data["photos"] = []
        result = _unpack_observation(observation_data)
        assert result["has_photo"] is False

    def test_has_recording_true_when_sounds_present(self, observation_data):
        observation_data["sounds"] = [{"id": 1}]
        result = _unpack_observation(observation_data)
        assert result["has_recording"] is True

    def test_has_recording_false_when_no_sounds(self, observation_data):
        result = _unpack_observation(observation_data)
        assert result["has_recording"] is False

    def test_missing_geojson_returns_none_coordinates(self, observation_data):
        del observation_data["geojson"]
        result = _unpack_observation(observation_data)
        assert result["longitude"] is None
        assert result["latitude"] is None

    def test_missing_private_geojson_returns_none_private_coordinates(self, observation_data):
        del observation_data["private_geojson"]
        result = _unpack_observation(observation_data)
        assert result["longitude_private"] is None
        assert result["latitude_private"] is None

    def test_missing_optional_fields_return_none(self, observation_data):
        del observation_data["description"]
        result = _unpack_observation(observation_data)
        assert result["description"] is None


# ---------------------------------------------------------------------------
# _unpack_identifications
# ---------------------------------------------------------------------------

class TestUnpackIdentifications:
    def test_returns_empty_lists_for_empty_input(self):
        ids, users = _unpack_identifications(1001, [], set())
        assert ids == []
        assert users == []

    def test_returns_empty_lists_for_none_input(self):
        ids, users = _unpack_identifications(1001, None, set())
        assert ids == []
        assert users == []

    def test_extracts_identification_fields(self, identification_data):
        ids, _ = _unpack_identifications(1001, [identification_data], set())
        assert ids[0]["observation_id"] == 1001
        assert ids[0]["identification_id"] == 501
        assert ids[0]["user_id"] == 10
        # assert ids[0]["current"] is True
        assert ids[0]["taxon_id"] == 99

    def test_adds_new_user(self, identification_data):
        _, users = _unpack_identifications(1001, [identification_data], set())
        assert len(users) == 1
        assert users[0]["id"] == 10

    def test_does_not_duplicate_known_user(self, identification_data):
        user_set = {10}
        _, users = _unpack_identifications(1001, [identification_data], user_set)
        assert users == []

    def test_updates_user_set_with_new_user(self, identification_data):
        user_set = set()
        _unpack_identifications(1001, [identification_data], user_set)
        assert 10 in user_set

    def test_multiple_identifications(self, identification_data):
        ident2 = {**identification_data, "id": 502, "user": {"id": 11, "login": "user2"}}
        ids, users = _unpack_identifications(1001, [identification_data, ident2], set())
        assert len(ids) == 2
        assert len(users) == 2


# ---------------------------------------------------------------------------
# _unpack_annotations
# ---------------------------------------------------------------------------

class TestUnpackAnnotations:
    def test_returns_none_for_empty_list(self):
        assert _unpack_annotations(1001, []) is None

    def test_returns_none_for_none_input(self):
        assert _unpack_annotations(1001, None) is None

    def test_extracts_annotation_fields(self):
        annotation = {
            "controlled_attribute_id": 1,
            "controlled_value_id":     2,
            "user_id":                 42,
            "vote_score":              1,
        }
        result = _unpack_annotations(1001, [annotation])
        assert result[0]["observation_id"] == 1001
        assert result[0]["annotation_id"] == 1
        assert result[0]["value_id"] == 2
        assert result[0]["user_id"] == 42
        assert result[0]["vote_score"] == 1

    def test_multiple_annotations(self):
        annotations = [
            {"controlled_attribute_id": 1, "controlled_value_id": 2, "user_id": 1, "vote_score": 1},
            {"controlled_attribute_id": 3, "controlled_value_id": 4, "user_id": 2, "vote_score": 1},
        ]
        result = _unpack_annotations(1001, annotations)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _unpack_results
# ---------------------------------------------------------------------------

class TestUnpackResults:
    def test_adds_observation(self, observation_data):
        results = ObservationResults()
        _unpack_results([observation_data], results, set())
        assert len(results.observations) == 1
        assert results.observations[0]["observation_id"] == 1001

    def test_processes_all_observations_in_list(self):
        """Catches the bug where return inside the for loop exits after the first result."""
        data = [make_observation(1001, user_id=1), make_observation(1002, user_id=2)]
        results = ObservationResults()
        _unpack_results(data, results, set())
        assert len(results.observations) == 2

    def test_returns_updated_users_set(self, observation_data):
        results = ObservationResults()
        users_set = set()
        returned_set = _unpack_results([observation_data], results, users_set)
        assert 1 in returned_set

    def test_adds_observer_to_users(self, observation_data):
        results = ObservationResults()
        users_set = set()
        users_set = _unpack_results([observation_data], results, users_set)
        assert 1 in users_set
        assert any(u["id"] == 1 for u in results.users)

    def test_does_not_duplicate_observer(self, observation_data):
        results = ObservationResults()
        users_set = {42}
        _unpack_results([observation_data], results, users_set)
        assert not any(u["id"] == 42 for u in results.users)

    def test_adds_identifications(self, observation_data, identification_data):
        observation_data["identifications"] = [identification_data]
        results = ObservationResults()
        _unpack_results([observation_data], results, set())
        assert len(results.identifications) == 1

    def test_adds_annotations(self, observation_data):
        observation_data["annotations"] = [
            {"controlled_attribute_id": 1, "controlled_value_id": 2, "user_id": 1, "vote_score": 1}
        ]
        results = ObservationResults()
        _unpack_results([observation_data], results, set())
        assert len(results.annotations) == 1

    def test_skips_annotations_when_empty(self, observation_data):
        results = ObservationResults()
        _unpack_results([observation_data], results, set())
        assert results.annotations == []


# ---------------------------------------------------------------------------
# fetch_observations
# ---------------------------------------------------------------------------

class TestFetchObservations:
    def test_returns_early_when_no_taxa_after_date_filter(self, auth, config):
        today = str(dt.date.today())
        df = pd.DataFrame({"taxon_id": [1], "date_updated": [today]})
        config.update_after_days = 30

        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._create_date_taxon_map") as mock_func:
                fetch_observations(auth, df, config)

                assert mock_func.call_count == 0

    def test_returns_observation_results(self, auth, config, taxa_df, observation_data):
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch", return_value=[observation_data]):
                result = fetch_observations(auth, taxa_df, config)

        assert isinstance(result, ObservationResults)
        assert len(result.observations) > 0

    def test_completed_taxa_populated(self, auth, config, taxa_df, observation_data):
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch", return_value=[observation_data]):
                result = fetch_observations(auth, taxa_df, config)

        assert len(result.completed_taxa) > 0

    def test_stops_at_max_observations(self, auth, config, taxa_df, observation_data):
        config.max_observations = 0
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch", return_value=[observation_data]):
                result = fetch_observations(auth, taxa_df, config)

        assert len(result.completed_taxa) < len(taxa_df)

    def test_project_id_added_to_params_when_set(self, auth, config, taxa_df, observation_data):
        config.project_id = 999
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                fetch_observations(auth, taxa_df, config)

        called_params = mock_request.call_args[0][1]
        assert called_params.get("project_id") == 999

    def test_project_id_not_in_params_when_none(self, auth, config, taxa_df, observation_data):
        config.project_id = None
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                fetch_observations(auth, taxa_df, config)

        called_params = mock_request.call_args[0][1]
        assert "project_id" not in called_params

    def test_created_d1_set_for_dated_taxa(self, auth, config, observation_data):
        df = pd.DataFrame({
            "taxon_id":     [1, 2],
            "date_updated": ["2023-01-01", "2023-01-01"],
        })
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                fetch_observations(auth, df, config)

        called_params = mock_request.call_args[0][1]
        assert called_params.get("created_d1") == "2023-01-01"

    def test_input_dataframe_not_mutated(self, auth, config, taxa_df, observation_data):
        original_dates = taxa_df["date_updated"].copy()
        with patch("inatdatapipeline.client.observations._get_fields_rison", return_value="fields"):
            with patch("inatdatapipeline.client.observations._request_batch", return_value=[observation_data]):
                fetch_observations(auth, taxa_df, config)

        pd.testing.assert_series_equal(taxa_df["date_updated"], original_dates)
