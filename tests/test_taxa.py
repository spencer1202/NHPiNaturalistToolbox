from unittest.mock import MagicMock, patch
import logging
import pytest
import warnings
import pandas as pd

from inatdatapipeline.client.taxa import (
    Taxon,
    TaxonMappingBuilder
)

# Set up logging
logger = logging.getLogger('pipeline')

# ---------------------------------------------------------------------------
# Data Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tracking_df():
    return pd.DataFrame({
        "est_id":            [1, 2, 3],
        "sci_name":          ["Aster alpinus var. vierhapperi", "Carex stipata", "Salix sp. 12"],
        "element_type":      ["Plant", "Plant", "Plant"],
        "scientific_name":   ["<i>Aster alpinus var. vierhapperi</i>", "<i>Carex stipata</i>", "<i>Salix sp. 12</i>"],
        "common_name":       ["Alpine Aster", "Tussock Sedge", "Willow"],
        "element_name":      ["1", "2", "3"],
        "family":            ["Asteraceae", "Cyperaceae", "Salicaceae"],
        "author":            ["L.", "Aiton", "L."],
        "egt_uid":           ["uid1", "uid2", "uid3"],
        "srank":             ["S1", "S2", "S3"],
        "track_status":      ["Track", "Track", "Track"],
        "explorer":          ["url1", "url2", "url3"],
        "explorer_link":     ["link1", "link2", "link3"],
        "elcode":            ["code1", "code2", "code3"],
        "growth_habit":      ["Forb", "Graminoid", "Shrub"],
        "duration":          ["Perennial", "Perennial", "Perennial"],
    })

@pytest.fixture
def preprocessed_df(tracking_df):
    """Tracking df with search_name and exact_match already set."""
    df = tracking_df.copy()
    df["search_name"] = ["Aster alpinus", "Carex stipata", "Salix"]
    df["is_described"]    = [True, True, False]
    return df

@pytest.fixture
def overrides_df():
    return pd.DataFrame({
        "est_id":    [1],
        "inat_name": ["Aster alpinus"],
        "taxon_id":  [None]
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_api_response(results: list) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": results}
    return mock_response


def make_taxon_result(id=123, name="Carex stipata"):
    return Taxon(id, name)

# ---------------------------------------------------------------------------
# preprocess_name
# ---------------------------------------------------------------------------
class TestPreprocessName:
    def test_removes_var(self):
        assert TaxonMappingBuilder._preprocess_names("Plagiochila semidecurrens var. semidecurrens") == "Plagiochila semidecurrens semidecurrens"
    
    def test_removes_ssp(self):
        assert TaxonMappingBuilder._preprocess_names("Sidalcea malviflora ssp. patula") == "Sidalcea malviflora patula"
    
    def test_removes_pop(self):
        assert TaxonMappingBuilder._preprocess_names("Salvelinus confluentus pop. 25") == "Salvelinus confluentus 25"
    
    def test_removes_sp(self):
         assert TaxonMappingBuilder._preprocess_names("Salix sp. 12") == "Salix 12"
        
    def test_plain_binomial_unchanged(self):
        assert TaxonMappingBuilder._preprocess_names("Sardinops sagax") == "Sardinops sagax"

    def test_none_returns_none(self):
        assert TaxonMappingBuilder._preprocess_names(None) is None

    def test_nan_returns_none(self):
        assert TaxonMappingBuilder._preprocess_names(float("nan")) is None
    
    def test_empty_string_returns_none(self):
        assert TaxonMappingBuilder._preprocess_names("") is None
    
    def test_cleans_double_spaces(self):
        result = TaxonMappingBuilder._preprocess_names("Aster  alpinus")
        assert "  " not in result

    def test_single_word_name_passes_through_unchanged(self):
        """A bare genus-only name has no var./ssp./pop. suffix to strip, so it should
        pass through unchanged rather than returning None."""
        assert TaxonMappingBuilder._preprocess_names("Bacteria") == "Bacteria"

    def test_single_word_name_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="pipeline"):
            TaxonMappingBuilder._preprocess_names("Bacteria")
        assert "Bacteria" in caplog.text
    

# ---------------------------------------------------------------------------
# get_undescribed_names
# ---------------------------------------------------------------------------
class TestGetUndescribedNames:
    def test_marks_described_taxa_as_described(self):
        names = pd.Series(["Carex stipata", "Aster alpinus"])
        result = TaxonMappingBuilder.get_undescribed_names(names)
        assert ~result.any()

    def test_marks_undescribed_taxa(self):
        names = pd.Series(["Salix 12", "Carex stipata"])
        result = TaxonMappingBuilder.get_undescribed_names(names)
        assert result.loc[0]
        assert not result.loc[1]
    
    def test_extracts_generic_name(self):
        names = pd.Series(["Salix 12"])
        result = TaxonMappingBuilder.get_undescribed_names(names)
        assert result.loc[0] == "Salix"
    
    def test_preserved_described_name(self):
        names = pd.Series(["Salix 12", "Carex stipata"])
        result = TaxonMappingBuilder.get_undescribed_names(names)
        assert result.loc[1] == ""

    def test_single_word_name_marked_undescribed(self):
        """
        A single-word name (genus only, no species epithet) represents an unidentified
        species and should be treated as undescribed, with the generic name equal to itself.
        """
        names = pd.Series(["Bacteria", "Carex stipata"])
        result = TaxonMappingBuilder.get_undescribed_names(names)
        assert result.loc[0] == "Bacteria"
        assert result.loc[1] == ""

    def test_no_downcasting_future_warning(self):
        names = pd.Series(["Carex stipata", "Aster alpinus"])
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            TaxonMappingBuilder.get_undescribed_names(names) # should not raise

# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------
class TestPreprocess:
    def test_applies_overrides(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 1, "search_name"].iloc[0] == "Aster alpinus"
        
    def test_non_overriden_names_preprocessed(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 2, "search_name"].iloc[0] == "Carex stipata"
        
    def test_undescribed_taxa_marked(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert not result.loc[result["est_id"] == 3, "is_described"].iloc[0]

    def test_described_taxa_marked(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 2, "is_described"].iloc[0]

    def test_override_not_matching_any_tracking_row_ignored(self, tracking_df, overrides_df):
        """
        An override row whose est_id doesn't correspond to any row in the tracking list
        should be ignored, leaving that row's own sci_name preprocessing in place.
        """
        df = overrides_df.copy()
        df["est_id"] = [999]
        df["inat_name"] = ["Should Not Apply"]

        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, df)

        assert result.loc[result["est_id"] == 1, "search_name"].iloc[0] == "Aster alpinus vierhapperi"
        assert "Should Not Apply" not in result["search_name"].values


# ---------------------------------------------------------------------------
# query_taxon
# ---------------------------------------------------------------------------
class TestQueryTaxon:
    def test_returns_exact_match_as_primary(self, auth):
        api_results = [
            {"id": 123, "name": "Carex stipata"},
            {"id": 456, "name": "Carex stipata var. maxima"}
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)
        
        assert result is not None
        assert result.taxon_id == 123
        assert result.name == "Carex stipata"

    def test_no_exact_match_uses_first_result(self, auth):
        api_results = [
            {"id": 789, "name": "Carex stipata var. maxima"},
            {"id": 101, "name": "Carex stipata subsp. other"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.taxon_id == 789
    
    def test_override_id_match_uses_result(self, auth):
        api_results = [
            {"id": 789, "name": "Carex stipata var. maxima"},
            {"id": 101, "name": "Carex stipata subsp. other"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Arbitrary name", auth, 101)
        
        assert result.taxon_id == 101
        assert result.name == "Carex stipata subsp. other"
    
    def test_empty_results_returns_none(self, auth):
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response([])
            result = TaxonMappingBuilder.query_taxon("Nonexistent taxon", auth)

        assert result is None
    
    def test_network_error_returns_none(self, auth, caplog):
        import requests as req
        with caplog.at_level(logging.ERROR, logger="pipeline"):
            with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
                mock_get.side_effect = req.RequestException("Network error")
                result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert "Error looking up 'Carex stipata': " in caplog.text
        assert result is None

    def test_http_error_returns_none(self, auth, caplog):
        """A non-2xx response (raise_for_status raising HTTPError) should be handled the
        same as any other RequestException, since HTTPError is a subclass of it."""
        import requests as req
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        with caplog.at_level(logging.ERROR, logger="pipeline"):
            with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
                mock_get.return_value = mock_response
                result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert "Error looking up 'Carex stipata': " in caplog.text
        assert result is None
    
    def test_invalid_taxon_id_skipped(self, auth):
        api_results = [
            {"id": None, "name": "Carex stipata"},
            {"id": 456,  "name": "Carex stipata var. maxima"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result is not None
        assert result.taxon_id == 456

    def test_non_numeric_id_skipped(self, auth, caplog):
        """A non-numeric id (e.g. a malformed API response) should be skipped like any
        other invalid id, not raise."""
        api_results = [
            {"id": "abc", "name": "Carex stipata"},
            {"id": 456,   "name": "Carex stipata maxima"},
        ]
        with caplog.at_level(logging.ERROR, logger="pipeline"):
            with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
                mock_get.return_value = make_api_response(api_results)
                result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert "Skipping malformed result." in caplog.text
        assert result is not None
        assert result.taxon_id == 456

    def test_alternative_skips_invalid_first_result(self, auth):
        """If the first result has an invalid id, the first *valid* result should become
        the fallback alternative rather than being dropped along with it."""
        api_results = [
            {"id": None, "name": "Carex stipata maxima"},
            {"id": 789,  "name": "Carex stipata"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.taxon_id == 789

    def test_case_insensitive_exact_match(self, auth):
        api_results = [{"id": 123, "name": "carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.taxon_id == 123

    def test_sends_q_param_for_name_search(self, auth):
        """When no taxon_id override is given, the request should search by name (q)
        and should NOT include a taxon_id param."""
        api_results = [{"id": 123, "name": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "Carex stipata"
        assert "taxon_id" not in kwargs["params"]

    def test_sends_taxon_id_param_for_override_search(self, auth):
        """When a taxon_id override is given, the request should search by that id
        and should NOT include a q param."""
        api_results = [{"id": 123, "name": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            TaxonMappingBuilder.query_taxon("Carex stipata", auth, taxon_id=123)

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["taxon_id"] == 123
        assert "q" not in kwargs["params"]

# ---------------------------------------------------------------------------
# get_new_mappings
# ---------------------------------------------------------------------------
class TestGetNewMappings:
    def test_returns_empty_df_when_no_results(self, preprocessed_df, auth):
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=None):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, count = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)
        
        assert len(result) == 0
        assert isinstance(result, pd.DataFrame)
        assert count == 3

    def test_returns_mapping_result(self, preprocessed_df, auth):
        taxon_results = [
            make_taxon_result(id=i)
            for i in range(len(preprocessed_df))
        ]

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=taxon_results):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, count = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)

        assert result is not None
        assert count == 3

    def test_undescribed_taxa_queried_once(self, preprocessed_df, auth):
        """The same undescribed taxon name should only be queried onece."""
        df = preprocessed_df.copy()
        df["search_name"] = ["Salix", "Salix", "Salix"]
        df["is_described"] = [False, False, False]

        taxon_results = iter([
            make_taxon_result(id=i)
            for i in range(len(df))
        ])

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=lambda name, auth, override_id: next(taxon_results)) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                TaxonMappingBuilder.get_new_mappings(auth, df)
        
        assert mock_query.call_count == 1
    
    def test_override_map_is_used(self, preprocessed_df, auth):
        override_map = {
            2: 101
        }
        taxon_results = iter([
            make_taxon_result(id=i, name=f"Name {i}")
            for i in [1, 101, 3]
        ])

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=lambda name, auth, override_id: next(taxon_results)) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, _ = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df, override_map)

        # The second time query_taxon is called, the third argument should be the override id
        assert mock_query.call_args_list[1].args[2] == 101
        assert mock_query.call_args_list[0].args[2] is None
        assert mock_query.call_args_list[2].args[2] is None

    def test_undescribed_taxa_not_found_still_only_queried_once(self, preprocessed_df, auth):
        """
        A not-found result for an undescribed taxon name should still be cached, so repeat
        occurrences of that name don't trigger repeat API calls.
        """
        df = preprocessed_df.copy()
        df["search_name"] = ["Salix", "Salix", "Salix"]
        df["is_described"] = [False, False, False]

        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=None) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, count = TaxonMappingBuilder.get_new_mappings(auth, df)

        assert mock_query.call_count == 1
        assert count == 1
        assert len(result) == 0

    def test_distinct_undescribed_names_queried_separately(self, preprocessed_df, auth):
        """Two different undescribed names should each be queried once (not conflated
        with each other), while a repeat of either reuses its own cached result."""
        df = preprocessed_df.copy()
        df["search_name"] = ["Salix", "Carex", "Salix"]
        df["is_described"] = [False, False, False]

        taxon_results = iter([
            make_taxon_result(id=1, name="Salix"),
            make_taxon_result(id=2, name="Carex"),
        ])

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=lambda name, auth, override_id: next(taxon_results)) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, count = TaxonMappingBuilder.get_new_mappings(auth, df)

        assert mock_query.call_count == 2
        assert count == 2
        assert len(result) == 3  # third row reuses the cached "Salix" result

    def test_mixed_found_and_not_found_undescribed_batch(self, preprocessed_df, auth):
        """Undescribed rows mixing a name that matches and a name that doesn't should
        each be queried once, and only the matched name's rows should appear in results."""
        df = preprocessed_df.copy()
        df["search_name"] = ["Salix", "Salix", "Quercus"]
        df["is_described"] = [False, False, False]

        results_by_name = {
            "Salix": make_taxon_result(id=42, name="Salix sp."),
            "Quercus": None,
        }

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=lambda name, auth, override_id: results_by_name[name]) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, count = TaxonMappingBuilder.get_new_mappings(auth, df)

        assert mock_query.call_count == 2
        assert count == 2
        assert len(result) == 2
        assert (result["taxon_id"] == 42).all()

    def test_original_row_fields_preserved_in_result(self, preprocessed_df, auth):
        """Fields already present on the tracking row (e.g. sci_name, est_id) should be
        carried through into the result, alongside the new taxon_id/inat_name fields."""
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=make_taxon_result(id=999, name="Match")):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result, _ = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)

        assert "sci_name" in result.columns
        assert "est_id" in result.columns
        assert (result["taxon_id"] == 999).all()
        assert (result["inat_name"] == "Match").all()

    def test_sleep_called_once_per_row(self, preprocessed_df, auth):
        """The pipeline should pause once per processed row, regardless of match result,
        to stay within API rate limits."""
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=None):
            with patch("inatdatapipeline.client.taxa.time.sleep") as mock_sleep:
                TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)

        assert mock_sleep.call_count == len(preprocessed_df)


# ---------------------------------------------------------------------------
# build_override_id_map
# ---------------------------------------------------------------------------
class TestBuildOverrideIdMap:
    def test_maps_est_id_to_taxon_id(self, overrides_df):
        df = overrides_df.copy()
        df["taxon_id"] = [100]

        result = TaxonMappingBuilder.build_override_id_map(df)

        assert result == {1: 100}

    def test_drops_rows_with_nan_taxon_id(self, overrides_df):
        df = pd.concat([overrides_df, overrides_df.copy(), overrides_df.copy()], ignore_index=True)
        df["est_id"] = [1, 2, 3]
        df["taxon_id"] = [100, None, 300]

        result = TaxonMappingBuilder.build_override_id_map(df)

        assert result == {1: 100, 3: 300}
        assert 2 not in result

    def test_empty_df_returns_empty_dict(self, overrides_df):
        df = overrides_df.iloc[0:0]

        result = TaxonMappingBuilder.build_override_id_map(df)

        assert result == {}

    def test_empty_when_only_name_overrides_present(self, overrides_df):
        """The fixture's default row provides a name override with no taxon_id, which
        should yield no id mappings at all."""
        result = TaxonMappingBuilder.build_override_id_map(overrides_df)
        assert result == {}


# ---------------------------------------------------------------------------
# build_mapping
# ---------------------------------------------------------------------------
class TestGetToMatch:
    def test_raises_on_none_or_empty_tracking_df(self):
        builder = TaxonMappingBuilder()
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            builder.get_to_match(pd.DataFrame(), None)
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            builder.get_to_match(None, None)
        
    def test_filters_already_mapped_taxa(self, preprocessed_df):
        builder = TaxonMappingBuilder()
        mapping_df = pd.DataFrame({"est_id": [1, 2]})

        result_df = builder.get_to_match(preprocessed_df, mapping_df)
        
        assert len(result_df) == 1
        assert result_df.iloc[0]["est_id"] == 3

    def test_returns_none_when_all_already_mapped(self, preprocessed_df, auth):
        builder = TaxonMappingBuilder()
        mapping_df = pd.DataFrame({"est_id": [1, 2, 3]})
        result = builder.get_to_match(preprocessed_df, mapping_df)
        assert len(result) == 0

    def test_none_mapping_df_maps_all_taxa(self, preprocessed_df, auth):
        builder = TaxonMappingBuilder()

        result = builder.get_to_match(preprocessed_df, None)
        
        assert len(result) == 3

    def test_returns_only_needed_columns(self, preprocessed_df):
        """The result should contain exactly sci_name, search_name, est_id, and
        is_described - no extra columns carried over from the tracking df."""
        builder = TaxonMappingBuilder()
        mapping_df = pd.DataFrame({"est_id": []})

        result_df = builder.get_to_match(preprocessed_df, mapping_df)

        assert list(result_df.columns) == ["sci_name", "search_name", "est_id", "is_described"]