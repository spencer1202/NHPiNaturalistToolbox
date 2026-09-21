"""
Tests for inatdatapipeline/client/observations.py
"""
import datetime as dt
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from inatdatapipeline.client.observations import (
    ObservationResults,
    ObservationDownloader
)
from inatdatapipeline.schemas import config, validation

# ---------------------------------------------------------------------------
# Data Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cfg():
    return config.ObservationsConfig(
        place_id=10,
        quality_grade="research",
        per_page=200,
        batch_size=30,
        update_after_days=7,
        max_observations=10000,
        project_id=247148,
    )

@pytest.fixture
def downloader(cfg, auth):
    return ObservationDownloader(cfg, auth)

@pytest.fixture
def taxa_df():
    return make_taxa_df(
        [1, 2, 3, 4],
        ["2026-01-01", "2026-01-01", "2026-01-01", None],
        match_type=["exact", "exact", "parent", "exact"],
    )

@pytest.fixture
def described_taxa_df():
    """Taxa dataframe with a mix of match types, for filter_taxa tests."""
    return make_taxa_df(
        [1, 2, 3, 4],
        ["2026-01-01", "2026-01-01", "2026-01-01", None],
        match_type=["exact", "exact", "parent", "exact"],
    )

@pytest.fixture
def observation_data():
    """A minimal valid iNaturalist observation dict."""
    return {
        "id"                                : 1001,
        "uuid"                              : ["j483js81", "hjfs923j589"],
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
def raw_observation_df():
    """Minimal valid raw observation dataframe with string dates."""
    return pd.DataFrame({
        "observation_id":               [1, 2],
        "uuid":                         ["j483js81", "hjfs923j589"],
        "observer_id":                  [10, 11],
        "taxon_id":                     [99, 100],
        "license":                      ["cc-by", None],
        "latitude":                     [37.8, 38.0],
        "longitude":                    [-122.4, -123.0],
        "latitude_private":             [None, 37.9],
        "longitude_private":            [None, -122.5],
        "coordinate_precision":         [10, None],
        "coordinate_precision_public":  [50, None],
        "observed_on_string":           ["March 15, 2024", "March 16, 2024"],
        "quality_grade":                ["research", "needs_id"],
        "url":                          ["https://inaturalist.org/1", "https://inaturalist.org/2"],
        "description":                  ["Found near stream", None],
        "id_agreements":                [3, 0],
        "id_disagreements":             [0, 1],
        "captive_cultivated":           [False, True],
        "place_guess":                  ["Near creek", "In forest"],
        "place_guess_private":          [None, "123 Private St"],
        "obscured":                     [False, True],
        "has_photo":                    [True, False],
        "has_recording":                [False, True],
        "observed_on":                  ["2024-03-15T00:00:00+00:00", "2024-03-16T00:00:00+00:00"],
        "created_at":                   ["2024-03-16T10:00:00+00:00", "2024-03-17T10:00:00+00:00"],
        "updated_at":                   ["2024-03-17T10:00:00+00:00", "2024-03-18T10:00:00+00:00"],
    })

@pytest.fixture
def clean_observation_df(raw_observation_df):
    """Raw observations passed through from_raw."""
    return validation.ObservationSchema.from_raw(raw_observation_df)

@pytest.fixture
def identification_data():
    return {
        "id":           501,
        "user":         {"id": 10, "login": "identifier1", "name": "Identifier One"},
        "created_at":   "2024-03-16T12:00:00Z",
        "taxon":        {"id": 99},
    }

@pytest.fixture
def raw_identifications_df():
    return pd.DataFrame({
        "observation_id":   [1, 1, 2],
        "user_id":          [10, 11, 12],
        "identification_id":[501, 502, 503],
        "created_at":       ["2024-03-16T12:00:00+00:00", "2024-03-16T13:00:00+00:00", "2024-03-17T10:00:00+00:00"],
        "current":          [True, False, True],
        "taxon_id":         [99, 98, 100],
    })

@pytest.fixture
def clean_identifications_df(raw_identifications_df):
    return validation.IdentificationsSchema.from_raw(raw_identifications_df)

@pytest.fixture
def users_df():
    return pd.DataFrame({
        "user_id":  [1, 2, 3],
        "login":    ["user1", "user2", "user3"],
        "name":     ["User One", None, "User Three"],
    })

@pytest.fixture
def annotations_df():
    return pd.DataFrame({
        "observation_id"    : [1, 1, 2],
        "annotation_id"     : [1, 9, 17],
        "value_id"          : [2, 2, 18],
        "user_id"           : [10, 1, 2],
        "vote_score"        : [0, -1, 1]
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_taxa_df(taxon_ids: list, date_updated: list, match_type: list = None) -> pd.DataFrame:
    """
    Factory for a full-schema mappings dataframe. Non-essential columns are filled with
    placeholder values derived from each taxon_id. match_type defaults to 'exact' for every row
    unless overridden.
    """
    if match_type is None:
        match_type = ["exact"] * len(taxon_ids)
    return pd.DataFrame({
        "est_id":               [200 + tid for tid in taxon_ids],
        "egt_id":                [300 + tid for tid in taxon_ids],
        "elcode":                [f"AAAA{tid:04d}" for tid in taxon_ids],
        "sci_name":              [f"Taxon {tid} sci" for tid in taxon_ids],
        "override_name":         [None for _ in taxon_ids],
        "parent_egt_id":         [None for _ in taxon_ids],
        "parent_sci_name":       [None for _ in taxon_ids],
        "genus_egt_id":          [None for _ in taxon_ids],
        "genus_sci_name":        [None for _ in taxon_ids],
        "common_name":           [f"Taxon {tid}" for tid in taxon_ids],
        "classification_level":  ["Species" for _ in taxon_ids],
        "is_described":          [True for _ in taxon_ids],
        "match_element_id":      [200 + tid for tid in taxon_ids],
        "taxon_id":              taxon_ids,
        "inat_name":             [f"Taxon {tid} sci" for tid in taxon_ids],
        "date_updated":          date_updated,
        "match_type":            match_type,
    })

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
# ObservationDownloader
# ---------------------------------------------------------------------------
class TestObservationDownloaderInit:
    def test_initial_stats_are_zero(self, downloader):
        assert downloader.request_count == 0
        assert downloader.total_taxa_count == 0
        assert downloader.filtered_taxa_count == 0
        assert downloader.undescribed_taxa_count == 0
        assert downloader.taxa_completed == 0
        assert downloader.exceeded_download_max is False


class TestGetBatches:
    def test_splits_evenly(self):
        result = list(ObservationDownloader._get_batches([1, 2, 3, 4], 2))
        assert result == [[1, 2], [3, 4]]

    def test_handles_remainder(self):
        result = list(ObservationDownloader._get_batches([1, 2, 3], 2))
        assert result == [[1, 2], [3]]

    def test_single_batch(self):
        result = list(ObservationDownloader._get_batches([1, 2, 3], 10))
        assert result == [[1, 2, 3]]

    def test_empty_list(self):
        result = list(ObservationDownloader._get_batches([], 5))
        assert result == []

    def test_batch_size_one(self):
        result = list(ObservationDownloader._get_batches([1, 2, 3], 1))
        assert result == [[1], [2], [3]]


class TestCreateDateTaxonMap:
    def test_groups_by_date(self):
        df = make_taxa_df([1, 2, 3], ["2024-01-01", "2024-01-01", "2024-02-01"])
        result = ObservationDownloader._create_date_taxon_map(df)
        assert result["2024-01-01"] == {1, 2}
        assert result["2024-02-01"] == {3}

    def test_null_dates_grouped_under_none_key(self):
        df = make_taxa_df([1, 2], [None, "2024-01-01"])
        result = ObservationDownloader._create_date_taxon_map(df)
        assert 1 in result["None"]

    def test_all_null_dates(self):
        df = make_taxa_df([1, 2], [None, None])
        result = ObservationDownloader._create_date_taxon_map(df)
        assert result["None"] == {1, 2}

    def test_no_null_dates_none_key_is_empty(self):
        df = make_taxa_df([1, 2], ["2024-01-01", "2024-02-01"])
        result = ObservationDownloader._create_date_taxon_map(df)
        assert result["None"] == set()


class TestApplyDateFilter:
    def test_none_update_days_clears_dates(self, cfg, auth, taxa_df):
        cfg.update_after_days = None
        downloader = ObservationDownloader(cfg, auth)
        result = downloader._apply_date_filter(taxa_df.copy())
        assert result["date_updated"].isna().all()

    def test_zero_update_days_clears_dates(self, cfg, auth, taxa_df):
        cfg.update_after_days = 0
        downloader = ObservationDownloader(cfg, auth)
        result = downloader._apply_date_filter(taxa_df.copy())
        assert result["date_updated"].isna().all()

    def test_does_not_mutate_input(self, downloader, taxa_df):
        original_dates = taxa_df["date_updated"].copy()
        downloader._apply_date_filter(taxa_df)
        pd.testing.assert_series_equal(taxa_df["date_updated"], original_dates)

    def test_filters_recently_updated_taxa(self, downloader):
        df = make_taxa_df(
            [1, 2],
            [
                str(dt.date.today() - dt.timedelta(days=1)),   # updated yesterday, filtered out
                str(dt.date.today() - dt.timedelta(days=30)),  # updated 30 days ago, kept
            ],
        )
        result = downloader._apply_date_filter(df)
        assert 1 not in result["taxon_id"].values
        assert 2 in result["taxon_id"].values

    def test_keeps_null_date_taxa(self, downloader):
        df = make_taxa_df([1], [None])
        result = downloader._apply_date_filter(df)
        assert len(result) == 1

    def test_keeps_taxa_updated_exactly_on_boundary(self, downloader):
        target = dt.date.today() - dt.timedelta(days=7)
        df = make_taxa_df([1], [str(target)])
        result = downloader._apply_date_filter(df)
        assert len(result) == 1


class TestFilterTaxa:
    def test_filters_out_parent_matches(self, downloader):
        df = make_taxa_df([1, 2], ["2026-01-01", "2026-01-01"], match_type=["exact", "parent"])
        result = downloader.filter_taxa(df)
        assert 2 not in result["taxon_id"].values
        assert 1 in result["taxon_id"].values

    def test_filters_out_genus_matches(self, downloader):
        df = make_taxa_df([1, 2], ["2026-01-01", "2026-01-01"], match_type=["exact", "genus"])
        result = downloader.filter_taxa(df)
        assert 2 not in result["taxon_id"].values
        assert 1 in result["taxon_id"].values

    def test_keeps_override_matches(self, downloader):
        df = make_taxa_df([1, 2], ["2026-01-01", "2026-01-01"], match_type=["exact", "override"])
        result = downloader.filter_taxa(df)
        assert 1 in result["taxon_id"].values
        assert 2 in result["taxon_id"].values

    def test_sets_total_taxa_count(self, downloader, described_taxa_df):
        downloader.filter_taxa(described_taxa_df)
        assert downloader.total_taxa_count == len(described_taxa_df)

    def test_sets_undescribed_taxa_count(self, downloader, described_taxa_df):
        """undescribed_taxa_count now tracks non-exact/override (parent/genus) matches,
        not literal undescribed status - the fixture has one 'parent' match type row."""
        downloader.filter_taxa(described_taxa_df)
        assert downloader.undescribed_taxa_count == 1

    def test_sets_filtered_taxa_count(self, downloader, described_taxa_df):
        result = downloader.filter_taxa(described_taxa_df)
        assert downloader.filtered_taxa_count == len(result)

    def test_does_not_mutate_input(self, downloader, described_taxa_df):
        original = described_taxa_df.copy()
        downloader.filter_taxa(described_taxa_df)
        pd.testing.assert_frame_equal(described_taxa_df, original)

    def test_applies_date_filter(self, downloader):
        df = make_taxa_df(
            [1, 2],
            [
                str(dt.date.today() - dt.timedelta(days=1)),   # too recent, filtered out
                str(dt.date.today() - dt.timedelta(days=30)),  # stale enough, kept
            ],
            match_type=["exact", "exact"],
        )
        result = downloader.filter_taxa(df)
        assert 1 not in result["taxon_id"].values
        assert 2 in result["taxon_id"].values


class TestRequestBatch:
    def test_returns_result_list(self, downloader):
        with patch(
            "inatdatapipeline.client.observations.helpers.sliding_page_requests",
            return_value=([{"id": 1}], 1),
        ):
            result = downloader._request_batch([1, 2], {}, "headers")

        assert result == [{"id": 1}]

    def test_increments_request_count(self, downloader):
        with patch(
            "inatdatapipeline.client.observations.helpers.sliding_page_requests",
            return_value=([], 3),
        ):
            downloader._request_batch([1, 2], {}, "headers")

        assert downloader.request_count == 3

    def test_request_count_accumulates_across_calls(self, downloader):
        with patch(
            "inatdatapipeline.client.observations.helpers.sliding_page_requests",
            return_value=([], 2),
        ):
            downloader._request_batch([1], {}, "headers")
            downloader._request_batch([2], {}, "headers")

        assert downloader.request_count == 4

    def test_sets_taxon_id_param(self, downloader):
        params = {}
        with patch(
            "inatdatapipeline.client.observations.helpers.sliding_page_requests",
            return_value=([], 0),
        ):
            downloader._request_batch([1, 2, 3], params, "headers")

        assert params["taxon_id"] == "1,2,3"


# ---------------------------------------------------------------------------
# _unpack_observation
# ---------------------------------------------------------------------------

class TestUnpackObservation:
    def test_extracts_basic_fields(self, observation_data):
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["observation_id"] == 1001
        assert result["observer_id"] == 1
        assert result["taxon_id"] == 99
        assert result["quality_grade"] == "research"

    def test_geojson_longitude_latitude_order(self, observation_data):
        # GeoJSON is [longitude, latitude]
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["longitude"] == -122.4
        assert result["latitude"] == 37.8

    def test_private_geojson_uses_private_field(self, observation_data):
        # Private coords should come from private_geojson, not geojson
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["longitude_private"] == -122.5234
        assert result["latitude_private"] == 37.2339

    def test_private_coords_differ_from_public(self, observation_data):
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["longitude_private"] != result["longitude"]
        assert result["latitude_private"] != result["latitude"]

    def test_has_photo_true_when_photos_present(self, observation_data):
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["has_photo"] is True

    def test_has_photo_false_when_no_photos(self, observation_data):
        observation_data["photos"] = []
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["has_photo"] is False

    def test_has_recording_true_when_sounds_present(self, observation_data):
        observation_data["sounds"] = [{"id": 1}]
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["has_recording"] is True

    def test_has_recording_false_when_no_sounds(self, observation_data):
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["has_recording"] is False

    def test_missing_geojson_returns_none_coordinates(self, observation_data):
        del observation_data["geojson"]
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["longitude"] is None
        assert result["latitude"] is None

    def test_missing_private_geojson_returns_none_private_coordinates(self, observation_data):
        del observation_data["private_geojson"]
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["longitude_private"] is None
        assert result["latitude_private"] is None

    def test_missing_optional_fields_return_none(self, observation_data):
        del observation_data["description"]
        result = ObservationDownloader._unpack_observation(observation_data)
        assert result["description"] is None


# ---------------------------------------------------------------------------
# _unpack_identifications
# ---------------------------------------------------------------------------

class TestUnpackIdentifications:
    def test_returns_empty_lists_for_empty_input(self):
        ids, users = ObservationDownloader._unpack_identifications(1001, [], set())
        assert ids == []
        assert users == []

    def test_returns_empty_lists_for_none_input(self):
        ids, users = ObservationDownloader._unpack_identifications(1001, None, set())
        assert ids == []
        assert users == []

    def test_extracts_identification_fields(self, identification_data):
        ids, _ = ObservationDownloader._unpack_identifications(1001, [identification_data], set())
        assert ids[0]["observation_id"] == 1001
        assert ids[0]["identification_id"] == 501
        assert ids[0]["user_id"] == 10
        assert ids[0]["taxon_id"] == 99

    def test_adds_new_user(self, identification_data):
        _, users = ObservationDownloader._unpack_identifications(1001, [identification_data], set())
        assert len(users) == 1
        assert users[0]["id"] == 10

    def test_does_not_duplicate_known_user(self, identification_data):
        user_set = {10}
        _, users = ObservationDownloader._unpack_identifications(1001, [identification_data], user_set)
        assert users == []

    def test_updates_user_set_with_new_user(self, identification_data):
        user_set = set()
        ObservationDownloader._unpack_identifications(1001, [identification_data], user_set)
        assert 10 in user_set

    def test_multiple_identifications(self, identification_data):
        ident2 = {**identification_data, "id": 502, "user": {"id": 11, "login": "user2"}}
        ids, users = ObservationDownloader._unpack_identifications(
            1001, [identification_data, ident2], set()
        )
        assert len(ids) == 2
        assert len(users) == 2


class TestUnpackAnnotations:
    def test_returns_none_for_empty_list(self):
        assert ObservationDownloader._unpack_annotations(1001, []) is None

    def test_returns_none_for_none_input(self):
        assert ObservationDownloader._unpack_annotations(1001, None) is None

    def test_extracts_annotation_fields(self):
        annotation = {
            "controlled_attribute_id": 1,
            "controlled_value_id":     2,
            "user_id":                 42,
            "vote_score":              1,
        }
        result = ObservationDownloader._unpack_annotations(1001, [annotation])
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
        result = ObservationDownloader._unpack_annotations(1001, annotations)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _unpack_results
# ---------------------------------------------------------------------------

class TestUnpackResults:
    def test_adds_observation(self, observation_data):
        results = ObservationResults()
        ObservationDownloader._unpack_results([observation_data], results, set(), set())
        assert len(results.observations) == 1
        assert results.observations[0]["observation_id"] == 1001

    def test_processes_all_observations_in_list(self):
        """Catches the bug where return inside the for loop exits after the first result."""
        data = [make_observation(1001, user_id=1), make_observation(1002, user_id=2)]
        results = ObservationResults()
        ObservationDownloader._unpack_results(data, results, set(), set())
        assert len(results.observations) == 2

    def test_returns_updated_users_and_observation_id_sets(self, observation_data):
        results = ObservationResults()
        users_set = set()
        id_set = set()
        returned_users_set, returned_id_set = (
            ObservationDownloader._unpack_results([observation_data], results, users_set, id_set)
        )
        assert 1 in returned_users_set
        assert 1001 in returned_id_set

    def test_adds_observer_to_users(self, observation_data):
        results = ObservationResults()
        users_set = set()
        users_set, _ = ObservationDownloader._unpack_results([observation_data], results, users_set, set())
        assert 1 in users_set
        assert any(u["id"] == 1 for u in results.users)

    def test_does_not_duplicate_observer(self, observation_data):
        results = ObservationResults()
        users_set = {42}
        ObservationDownloader._unpack_results([observation_data], results, users_set, set())
        assert not any(u["id"] == 42 for u in results.users)

    def test_adds_identifications(self, observation_data, identification_data):
        observation_data["identifications"] = [identification_data]
        results = ObservationResults()
        ObservationDownloader._unpack_results([observation_data], results, set(), set())
        assert len(results.identifications) == 1

    def test_adds_annotations(self, observation_data):
        observation_data["annotations"] = [
            {"controlled_attribute_id": 1, "controlled_value_id": 2, "user_id": 1, "vote_score": 1}
        ]
        results = ObservationResults()
        ObservationDownloader._unpack_results([observation_data], results, set(), set())
        assert len(results.annotations) == 1

    def test_skips_annotations_when_empty(self, observation_data):
        results = ObservationResults()
        ObservationDownloader._unpack_results([observation_data], results, set(), set())
        assert results.annotations == []

    # TODO add tests for handling duplicate observations

# ---------------------------------------------------------------------------
# fetch_observations
# ---------------------------------------------------------------------------

class TestFetchObservations:
    def test_raises_type_error_for_non_dataframe(self, downloader):
        with pytest.raises(TypeError):
            downloader.fetch_observations([1, 2, 3])

    def test_raises_value_error_for_empty_dataframe(self, downloader):
        empty_df = make_taxa_df([], [])
        with pytest.raises(ValueError):
            downloader.fetch_observations(empty_df)

    def test_returns_observation_results(self, downloader, taxa_df, observation_data):
        with patch.object(downloader, "_get_fields_rison", return_value = "fields"):
            with patch.object(downloader, "_request_batch", return_value=[observation_data]):
                result = downloader.fetch_observations(taxa_df)

        assert isinstance(result, ObservationResults)
        assert len(result.observations) > 0

    def test_completed_taxa_populated(self, downloader, taxa_df, observation_data):
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch", return_value=[observation_data]):
                result = downloader.fetch_observations(taxa_df)

        assert len(result.completed_taxa) > 0
        assert downloader.taxa_completed == len(result.completed_taxa)

    def test_stops_at_max_observations(self, downloader, taxa_df, observation_data):
        downloader.config.max_observations = 0
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch", return_value=[observation_data]):
                result = downloader.fetch_observations(taxa_df)

        assert len(result.completed_taxa) < len(taxa_df)
        assert downloader.exceeded_download_max is True

    def test_project_id_added_to_params_when_set(self, downloader, taxa_df, observation_data):
        downloader.config.project_id = 999
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                downloader.fetch_observations(taxa_df)

        called_params = mock_request.call_args[0][1]
        assert called_params.get("project_id") == 999

    def test_project_id_not_in_params_when_none(self, downloader, taxa_df, observation_data):
        downloader.config.project_id = None
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                downloader.fetch_observations(taxa_df)

        called_params = mock_request.call_args[0][1]
        assert "project_id" not in called_params

    def test_created_d1_set_for_dated_taxa(self, downloader, observation_data):
        df = make_taxa_df([1, 2], ["2023-01-01", "2023-01-01"])
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch") as mock_request:
                mock_request.return_value = [observation_data]
                downloader.fetch_observations(df)

        called_params = mock_request.call_args[0][1]
        assert called_params.get("created_d1") == "2023-01-01"

    def test_input_dataframe_not_mutated(self, downloader, taxa_df, observation_data):
        original_dates = taxa_df["date_updated"].copy()
        with patch.object(downloader, "_get_fields_rison", return_value="fields"):
            with patch.object(downloader, "_request_batch", return_value=[observation_data]):
                downloader.fetch_observations(taxa_df)

        pd.testing.assert_series_equal(taxa_df["date_updated"], original_dates)
