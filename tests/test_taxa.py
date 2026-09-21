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
        "est_id":            [1, 2, 3, 4],
        "egt_id":            [11, 12, 13, 14],
        "sci_name":          ["Aster alpinus var. vierhapperi", "Carex stipata", "Salix sp. 12", "Festuca rubra ssp. secunda"],
        "global_sci_name":   ["Aster alpinus var. vierhapperi", "Carex stipata", "Salix sp. 12", "Festuca rubra"],
        "classification_level": ["Variety", "Species", "Species", "Subspecies"],
        "parent_egt_id":     [101, None, None, None],
        "parent_sci_name":   ["Aster alpinus", None, None, None],
        "element_type":      ["Plant", "Plant", "Plant", "Plant"],
        "common_name":       ["Alpine Aster", "Tussock Sedge", "Willow", "Red Fescue"],
        "family":            ["Asteraceae", "Cyperaceae", "Salicaceae", "Poaceae"],
        "genus_egt_id":      [111, 112, 113, 114],
        "genus_sci_name":    ["Aster", "Carex", "Salix", "Festuca"],
        "author":            ["L.", "Aiton", "L.", "K."],
        "egt_uid":           ["uid1", "uid2", "uid3", "uid4"],
        "srank":             ["S1", "S2", "S3", "S1"],
        "track_status":      ["Track", "Track", "Track", "Track"],
        "explorer":          ["url1", "url2", "url3", "url3"],
        "elcode":            ["code1", "code2", "code3", "code4"],
        "growth_habit":      ["Forb", "Graminoid", "Shrub", "Shrub"],
        "duration":          ["Perennial", "Perennial", "Perennial", "Annual"],
    })

@pytest.fixture
def preprocessed_df(tracking_df):
    """
    Tracking df with the fields produced by preprocess_tracking_df already set, including
    parent_egt_id/parent_sci_name as they'd appear AFTER _fill_parent runs (est_id 4's
    parent info is filled from its own egt_id/global_sci_name since none was provided).
    """
    df = tracking_df.copy()
    df["sci_name_clean"] = ["Aster alpinus vierhapperi", "Carex stipata", "Salix 12", "Festuca rubra secunda"]
    df["override_name"]  = [None, None, None, None]
    df["is_described"]   = [True, True, False, True]
    df["parent_egt_id"]  = [101, None, None, 14]
    df["parent_sci_name"] = ["Aster alpinus", None, None, "Festuca rubra"]
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
# Taxon
# ---------------------------------------------------------------------------
class TestTaxon:
    def test_defaults_to_all_none(self):
        taxon = Taxon()
        assert taxon.taxon_name is None
        assert taxon.taxon_id is None
        assert taxon.est_id is None
        assert taxon.parent_egt_id is None
        assert taxon.genus_egt_id is None

    def test_get_mapping_record_shape(self):
        taxon = Taxon(taxon_name="Carex stipata", taxon_id=42, est_id=2)
        record = taxon.get_mapping_record()
        assert record == {
            "inat_name": "Carex stipata",
            "taxon_id": 42,
            "est_id": 2,
            "parent_egt_id": None,
            "genus_egt_id": None,
        }

    def test_get_mapping_record_with_parent_egt_id(self):
        taxon = Taxon(taxon_name="Festuca rubra", taxon_id=777, parent_egt_id=14)
        record = taxon.get_mapping_record()
        assert record["parent_egt_id"] == 14
        assert record["est_id"] is None

    def test_get_mapping_record_with_genus_egt_id(self):
        taxon = Taxon(taxon_name="Salix", taxon_id=888, genus_egt_id=113)
        record = taxon.get_mapping_record()
        assert record["genus_egt_id"] == 113
        assert record["est_id"] is None


# ---------------------------------------------------------------------------
# preprocess_name
# ---------------------------------------------------------------------------
class TestPreprocessName:
    def test_removes_var(self):
        assert TaxonMappingBuilder._preprocess_name("Plagiochila semidecurrens var. semidecurrens") == "Plagiochila semidecurrens semidecurrens"
    
    def test_removes_ssp(self):
        assert TaxonMappingBuilder._preprocess_name("Sidalcea malviflora ssp. patula") == "Sidalcea malviflora patula"
    
    def test_removes_pop(self):
        assert TaxonMappingBuilder._preprocess_name("Salvelinus confluentus pop. 25") == "Salvelinus confluentus 25"
    
    def test_removes_sp(self):
         assert TaxonMappingBuilder._preprocess_name("Salix sp. 12") == "Salix 12"
        
    def test_plain_binomial_unchanged(self):
        assert TaxonMappingBuilder._preprocess_name("Sardinops sagax") == "Sardinops sagax"

    def test_none_returns_none(self):
        assert TaxonMappingBuilder._preprocess_name(None) is None

    def test_nan_returns_none(self):
        assert TaxonMappingBuilder._preprocess_name(float("nan")) is None
    
    def test_empty_string_returns_none(self):
        assert TaxonMappingBuilder._preprocess_name("") is None
    
    def test_cleans_double_spaces(self):
        result = TaxonMappingBuilder._preprocess_name("Aster  alpinus")
        assert "  " not in result

    def test_single_word_name_passes_through_unchanged(self):
        """A bare genus-only name has no var./ssp./pop. suffix to strip, so it should
        pass through unchanged rather than returning None."""
        assert TaxonMappingBuilder._preprocess_name("Bacteria") == "Bacteria"

    def test_single_word_name_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="pipeline"):
            TaxonMappingBuilder._preprocess_name("Bacteria")
        assert "Bacteria" in caplog.text
    

# ---------------------------------------------------------------------------
# get_undescribed_names
# ---------------------------------------------------------------------------
class TestGetUndescribedNames:
    def test_marks_described_taxa_as_described(self):
        names = pd.Series(["Carex stipata", "Aster alpinus"])
        result = TaxonMappingBuilder._get_undescribed_names(names)
        assert ~result.any()

    def test_marks_undescribed_taxa(self):
        names = pd.Series(["Salix 12", "Carex stipata"])
        result = TaxonMappingBuilder._get_undescribed_names(names)
        assert result.loc[0]
        assert not result.loc[1]
    
    def test_extracts_generic_name(self):
        names = pd.Series(["Salix 12"])
        result = TaxonMappingBuilder._get_undescribed_names(names)
        assert result.loc[0] == "Salix"
    
    def test_preserved_described_name(self):
        names = pd.Series(["Salix 12", "Carex stipata"])
        result = TaxonMappingBuilder._get_undescribed_names(names)
        assert result.loc[1] == ""

    def test_single_word_name_marked_undescribed(self):
        """
        A single-word name (genus only, no species epithet) represents an unidentified
        species and should be treated as undescribed, with the generic name equal to itself.
        """
        names = pd.Series(["Bacteria", "Carex stipata"])
        result = TaxonMappingBuilder._get_undescribed_names(names)
        assert result.loc[0] == "Bacteria"
        assert result.loc[1] == ""

    def test_no_downcasting_future_warning(self):
        names = pd.Series(["Carex stipata", "Aster alpinus"])
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            TaxonMappingBuilder._get_undescribed_names(names) # should not raise


# ---------------------------------------------------------------------------
# _fill_parent
# ---------------------------------------------------------------------------
class TestFillParent:
    def test_fills_missing_parent_from_egt_id_and_global_name(self, tracking_df):
        """est_id 4 (Subspecies) has no parent info in the raw tracking data, so it
        should be filled from its own egt_id/global_sci_name."""
        parent_egt_id, parent_sci_name = TaxonMappingBuilder._fill_parent(tracking_df)

        row4 = tracking_df.index[tracking_df["est_id"] == 4][0]
        assert parent_egt_id.loc[row4] == 14
        assert parent_sci_name.loc[row4] == "Festuca rubra"

    def test_preserves_existing_parent_values(self, tracking_df):
        """est_id 1 (Variety) already has parent info set and shouldn't be overwritten."""
        parent_egt_id, parent_sci_name = TaxonMappingBuilder._fill_parent(tracking_df)

        row1 = tracking_df.index[tracking_df["est_id"] == 1][0]
        assert parent_egt_id.loc[row1] == 101
        assert parent_sci_name.loc[row1] == "Aster alpinus"


# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------
class TestPreprocess:
    def test_applies_overrides(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 1, "override_name"].iloc[0] == "Aster alpinus"
        assert result.loc[result["est_id"] == 1, "sci_name"].iloc[0] == "Aster alpinus var. vierhapperi"
        assert result.loc[result["est_id"] == 1, "sci_name_clean"].iloc[0] == "Aster alpinus vierhapperi"
        
    def test_non_overriden_names_preprocessed(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 4, "override_name"].iloc[0] is None
        assert result.loc[result["est_id"] == 4, "sci_name"].iloc[0] == "Festuca rubra ssp. secunda"
        assert result.loc[result["est_id"] == 4, "sci_name_clean"].iloc[0] == "Festuca rubra secunda"

    def test_parent_filled_with_global_name(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess_tracking_df(tracking_df, overrides_df)
        assert result.loc[result["est_id"] == 4, "override_name"].iloc[0] is None
        assert result.loc[result["est_id"] == 4, "sci_name_clean"].iloc[0] == "Festuca rubra secunda"
        assert result.loc[result["est_id"] == 4, "parent_sci_name"].iloc[0] == "Festuca rubra"
        assert result.loc[result["est_id"] == 4, "parent_egt_id"].iloc[0] == 14

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

        assert result.loc[result["est_id"] == 1, "sci_name_clean"].iloc[0] == "Aster alpinus vierhapperi"
        assert "Should Not Apply" not in result["override_name"].values


# ---------------------------------------------------------------------------
# _select_matching_id
# ---------------------------------------------------------------------------
class TestSelectMatchingId:
    def test_raises_on_none_results(self):
        with pytest.raises(ValueError, match="No results to select match from!"):
            TaxonMappingBuilder._select_matching_id(123, None)

    def test_raises_on_empty_results(self):
        with pytest.raises(ValueError, match="No results to select match from!"):
            TaxonMappingBuilder._select_matching_id(123, [])

    def test_returns_matching_result(self):
        results = [
            {"id": 111, "name": "Carex stipata"},
            {"id": 123, "name": "Carex stipata var. maxima"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_id(123, results)
        assert name == "Carex stipata var. maxima"
        assert taxon_id == 123

    def test_returns_none_none_when_no_match(self):
        results = [{"id": 111, "name": "Carex stipata"}]
        name, taxon_id = TaxonMappingBuilder._select_matching_id(999, results)
        assert name is None
        assert taxon_id is None

    def test_returns_first_match_when_duplicate_ids(self):
        results = [
            {"id": 123, "name": "First Match"},
            {"id": 123, "name": "Second Match"},
        ]
        name, _ = TaxonMappingBuilder._select_matching_id(123, results)
        assert name == "First Match"

# ---------------------------------------------------------------------------
# _select_matching_name
# ---------------------------------------------------------------------------
class TestSelectMatchingName:
    def test_raises_on_none_results(self):
        with pytest.raises(ValueError, match="No results to select match from!"):
            TaxonMappingBuilder._select_matching_name("Carex stipata", None)

    def test_raises_on_empty_results(self):
        with pytest.raises(ValueError, match="No results to select match from!"):
            TaxonMappingBuilder._select_matching_name("Carex stipata", [])

    def test_exact_name_match(self):
        results = [
            {"name": "Carex stipata var. maxima", "id": 1, "matched_term": "Carex stipata"},
            {"name": "Carex stipata", "id": 2, "matched_term": "Carex stipata"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name("Carex stipata", results)
        assert name == "Carex stipata"
        assert taxon_id == 2

    def test_matched_term_fallback_when_no_exact_name_match(self):
        results = [
            {"name": "Carex stipata var. maxima", "id": 1, "matched_term": "Carex stipata"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name("Carex stipata", results)
        assert name == "Carex stipata var. maxima"
        assert taxon_id == 1

    def test_exact_name_match_overrides_earlier_matched_term(self):
        """An earlier matched_term hit shouldn't win if a later result is an exact name match."""
        results = [
            {"name": "Carex stipata var. maxima", "id": 1, "matched_term": "Carex stipata"},
            {"name": "Carex stipata", "id": 2, "matched_term": "Carex stipata"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name("Carex stipata", results)
        assert name == "Carex stipata"
        assert taxon_id == 2

    def test_no_match_returns_none_none(self):
        """No fallback to a 'first result' guess anymore - a genuine non-match returns
        (None, None)."""
        results = [
            {"name": "Something Unrelated", "id": 1, "matched_term": "Something Else"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name("Carex stipata", results)
        assert name is None
        assert taxon_id is None

    def test_subrank_name_exact_match(self):
        results = [
            {"name": "Festuca rubra secunda", "id": 5, "matched_term": "Festuca rubra secunda"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name(
            "Festuca rubra", results, subrank_name="Festuca rubra secunda"
        )
        assert name == "Festuca rubra secunda"
        assert taxon_id == 5

    def test_subrank_name_matched_term_match(self):
        results = [
            {"name": "Festuca rubra ssp. secunda", "id": 5, "matched_term": "Festuca rubra secunda"},
        ]
        name, taxon_id = TaxonMappingBuilder._select_matching_name(
            "Festuca rubra", results, subrank_name="Festuca rubra secunda"
        )
        assert name == "Festuca rubra ssp. secunda"
        assert taxon_id == 5

# ---------------------------------------------------------------------------
# _make_taxon_request
# ---------------------------------------------------------------------------
class TestMakeTaxonRequest:
    def test_sends_q_param_when_no_override(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata")

        args, _ = mock_get.call_args
        params = args[1]
        assert params["q"] == "Carex stipata"
        assert "taxon_id" not in params

    def test_sends_taxon_id_param_for_override(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata", override_id=123)

        args, _ = mock_get.call_args
        params = args[1]
        assert params["taxon_id"] == 123
        assert "q" not in params

    def test_includes_rank_filter_for_classification_level(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata", classification_level="Species")

        args, _ = mock_get.call_args
        params = args[1]
        assert params["rank"] == "species"

    def test_omits_rank_filter_when_no_classification_level(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata")

        args, _ = mock_get.call_args
        params = args[1]
        assert "rank" not in params

    def test_increments_request_count(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata")
                builder._make_taxon_request("Carex stipata")

        assert builder.request_count == 2

    def test_returns_results_list(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = builder._make_taxon_request("Carex stipata")

        assert result == api_results

    def test_sleeps_once_per_request(self, auth):
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            with patch("inatdatapipeline.client.taxa.time.sleep") as mock_sleep:
                builder._make_taxon_request("Carex stipata")

        mock_sleep.assert_called_once_with(1)

    def test_warns_when_auth_headers_missing(self, auth, caplog):
        auth.get_auth_headers.return_value = None
        builder = TaxonMappingBuilder(auth)
        api_results = [{"id": 123, "name": "Carex stipata", "matched_term": "Carex stipata"}]
        with caplog.at_level(logging.WARNING, logger="pipeline"):
            with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
                mock_get.return_value = make_api_response(api_results)
                with patch("inatdatapipeline.client.taxa.time.sleep"):
                    builder._make_taxon_request("Carex stipata")

        assert "Could not retrieve iNaturalist authentication." in caplog.text

    def test_http_error_increments_error_count_and_returns_none(self, auth):
        import requests as req
        builder = TaxonMappingBuilder(auth)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = builder._make_taxon_request("Carex stipata")

        assert result is None
        assert builder.error_count == 1

    def test_connection_error_is_caught_and_counted(self, auth):
        """Connection-level failures (not just bad HTTP status) should also be caught and
        count toward the error threshold."""
        import requests as req
        builder = TaxonMappingBuilder(auth)
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.side_effect = req.ConnectionError("network down")
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = builder._make_taxon_request("Carex stipata")

        assert result is None
        assert builder.error_count == 1

    def test_timeout_is_caught_and_counted(self, auth):
        import requests as req
        builder = TaxonMappingBuilder(auth)
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.side_effect = req.Timeout("timed out")
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = builder._make_taxon_request("Carex stipata")

        assert result is None
        assert builder.error_count == 1

    def test_error_never_reads_response_body(self, auth):
        """A tolerated error should return None immediately, without attempting to parse a
        body from the failed response."""
        import requests as req
        builder = TaxonMappingBuilder(auth)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        mock_response.json.side_effect = AssertionError("json() should not be called on a failed response")
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = builder._make_taxon_request("Carex stipata")

        assert result is None
        mock_response.json.assert_not_called()

    def test_sleeps_on_error_path(self, auth):
        import requests as req
        builder = TaxonMappingBuilder(auth)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with patch("inatdatapipeline.client.taxa.time.sleep") as mock_sleep:
                builder._make_taxon_request("Carex stipata")

        mock_sleep.assert_called_once_with(1)

    def test_error_count_accumulates_across_calls(self, auth):
        import requests as req
        builder = TaxonMappingBuilder(auth)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                builder._make_taxon_request("Carex stipata")
                builder._make_taxon_request("Carex stipata")
                builder._make_taxon_request("Carex stipata")

        assert builder.error_count == 3

    def test_raises_after_five_errors(self, auth):
        import requests as req
        builder = TaxonMappingBuilder(auth)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("500 error")
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                for _ in range(4):
                    assert builder._make_taxon_request("Carex stipata") is None

                with pytest.raises(ValueError, match="Too many errors, aborting search"):
                    builder._make_taxon_request("Carex stipata")

        assert builder.error_count == 5

    def test_error_count_starts_at_zero(self, auth):
        builder = TaxonMappingBuilder(auth)
        assert builder.error_count == 0

# ---------------------------------------------------------------------------
# _search_all_ranks (dispatch)
# ---------------------------------------------------------------------------
class TestSearchAllRanks:
    def test_described_taxon_searches_normal(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 2].iloc[0].to_dict()  # Carex stipata
        with patch.object(builder, "_search_all_ranks_r") as mock_r:
            builder._search_all_ranks(record, set())
        mock_r.assert_called_once_with(record, set(), "normal")

    def test_undescribed_subrank_searches_parent(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 4].iloc[0].to_dict()  # Subspecies
        record["is_described"] = False
        with patch.object(builder, "_search_all_ranks_r") as mock_r:
            builder._search_all_ranks(record, set())
        mock_r.assert_called_once_with(record, set(), "parent")

    def test_undescribed_species_searches_genus(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 3].iloc[0].to_dict()  # Salix, Species, undescribed
        with patch.object(builder, "_search_all_ranks_r") as mock_r:
            builder._search_all_ranks(record, set())
        mock_r.assert_called_once_with(record, set(), "genus")


# ---------------------------------------------------------------------------
# _search_all_ranks_r (recursive core)
# ---------------------------------------------------------------------------
class TestSearchAllRanksRecursive:
    def test_invalid_search_type_raises(self, auth):
        builder = TaxonMappingBuilder(auth)
        with pytest.raises(ValueError, match="Invalid search type"):
            builder._search_all_ranks_r({}, set(), "bogus")

    def test_already_searched_name_skipped(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 2].iloc[0].to_dict()
        searched_set = {"Carex stipata"}
        with patch.object(builder, "_make_taxon_request") as mock_request:
            result = builder._search_all_ranks_r(record, searched_set, "normal")

        mock_request.assert_not_called()
        assert result is None

    def test_normal_search_adds_name_to_searched_set(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 2].iloc[0].to_dict()
        searched_set = set()
        with patch.object(builder, "_make_taxon_request", return_value=None):
            builder._search_all_ranks_r(record, searched_set, "normal")

        assert "Carex stipata" in searched_set

    def test_normal_search_found_match_sets_est_id(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 2].iloc[0].to_dict()
        api_results = [{"name": "Carex stipata", "id": 555, "matched_term": "Carex stipata"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results):
            result = builder._search_all_ranks_r(record, set(), "normal")

        assert result.taxon_name == "Carex stipata"
        assert result.taxon_id == 555
        assert result.est_id == 2

    def test_normal_search_falls_back_to_parent_then_genus(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 4].iloc[0].to_dict()  # has parent_egt_id
        with patch.object(builder, "_make_taxon_request", return_value=None) as mock_request:
            result = builder._search_all_ranks_r(record, set(), "normal")

        called_names = [call.args[0] for call in mock_request.call_args_list]
        assert called_names == ["Festuca rubra secunda", "Festuca rubra", "Festuca"]
        assert result is None

    def test_normal_search_skips_parent_when_no_parent_egt_id(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 3].iloc[0].to_dict()  # no parent
        with patch.object(builder, "_make_taxon_request", return_value=None) as mock_request:
            result = builder._search_all_ranks_r(record, set(), "normal")

        called_names = [call.args[0] for call in mock_request.call_args_list]
        called_levels = [call.args[1] for call in mock_request.call_args_list]
        assert called_levels == ["Species", "Genus"]
        assert called_names == ["Salix 12", "Salix"]
        assert result is None

    def test_parent_search_falls_back_to_genus(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 4].iloc[0].to_dict()
        with patch.object(builder, "_make_taxon_request", return_value=None) as mock_request:
            result = builder._search_all_ranks_r(record, set(), "parent")

        called_names = [call.args[0] for call in mock_request.call_args_list]
        assert called_names == ["Festuca rubra", "Festuca"]
        assert result is None

    def test_parent_search_found_match_sets_parent_egt_id(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 4].iloc[0].to_dict()
        api_results = [{"name": "Festuca rubra", "id": 777, "matched_term": "Festuca rubra"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results):
            result = builder._search_all_ranks_r(record, set(), "parent")

        assert result.taxon_name == "Festuca rubra"
        assert result.taxon_id == 777
        assert result.parent_egt_id == 14

    def test_parent_search_passes_subrank_name_to_select_matching_name(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 4].iloc[0].to_dict()
        api_results = [{"name": "Festuca rubra", "id": 777, "matched_term": "Festuca rubra"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results):
            with patch.object(TaxonMappingBuilder, "_select_matching_name", return_value=("Festuca rubra", 777)) as mock_select:
                builder._search_all_ranks_r(record, set(), "parent")

        mock_select.assert_called_once_with("Festuca rubra", api_results, "Festuca rubra secunda")

    def test_genus_search_returns_none_when_no_match(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 3].iloc[0].to_dict()
        with patch.object(builder, "_make_taxon_request", return_value=None) as mock_request:
            result = builder._search_all_ranks_r(record, set(), "genus")

        mock_request.assert_called_once_with("Salix", "Genus")
        assert result is None

    def test_genus_search_found_match_sets_genus_egt_id(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        record = preprocessed_df.loc[preprocessed_df["est_id"] == 3].iloc[0].to_dict()
        api_results = [{"name": "Salix", "id": 888, "matched_term": "Salix"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results):
            result = builder._search_all_ranks_r(record, set(), "genus")

        assert result.taxon_name == "Salix"
        assert result.taxon_id == 888
        assert result.genus_egt_id == 113


# ---------------------------------------------------------------------------
# _search_override
# ---------------------------------------------------------------------------
class TestSearchOverride:
    def test_name_override_uses_select_matching_name(self, auth, overrides_df):
        builder = TaxonMappingBuilder(auth)
        override_row = overrides_df.iloc[0]
        api_results = [{"name": "Aster alpinus", "id": 42, "matched_term": "Aster alpinus"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results) as mock_request:
            result = builder._search_override(override_row["inat_name"], override_row["est_id"], None)

        mock_request.assert_called_once_with("Aster alpinus", None, None)
        assert result.taxon_name == "Aster alpinus"
        assert result.taxon_id == 42
        assert result.est_id == 1

    def test_id_override_uses_select_matching_id(self, auth, overrides_df):
        builder = TaxonMappingBuilder(auth)
        override_row = overrides_df.iloc[0]
        api_results = [{"name": "Aster alpinus", "id": 42, "matched_term": "Aster alpinus"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results) as mock_request:
            result = builder._search_override(override_row["inat_name"], override_row["est_id"], 42)

        mock_request.assert_called_once_with("Aster alpinus", None, 42)
        assert result.taxon_id == 42
        assert result.est_id == 1

    def test_no_results_returns_none(self, auth, overrides_df):
        builder = TaxonMappingBuilder(auth)
        override_row = overrides_df.iloc[0]
        with patch.object(builder, "_make_taxon_request", return_value=None):
            result = builder._search_override(override_row["inat_name"], override_row["est_id"], None)

        assert result is None

    def test_no_match_returns_none(self, auth, overrides_df):
        builder = TaxonMappingBuilder(auth)
        override_row = overrides_df.iloc[0]
        api_results = [{"name": "Unrelated Name", "id": 1, "matched_term": "Something Else"}]
        with patch.object(builder, "_make_taxon_request", return_value=api_results):
            result = builder._search_override(override_row["inat_name"], override_row["est_id"], None)

        assert result is None


# ---------------------------------------------------------------------------
# create_new_mappings
# ---------------------------------------------------------------------------
class TestCreateNewMappings:
    def test_generates_access_token_when_missing(self, auth, preprocessed_df):
        auth.get_access_token.return_value = None
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()
        with patch.object(builder, "_search_all_ranks", return_value=None):
            builder.create_new_mappings(df, {})

        auth.generate_access_token.assert_called_once()

    def test_skips_generating_token_when_present(self, auth, preprocessed_df):
        auth.get_access_token.return_value = "existing-token"
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()
        with patch.object(builder, "_search_all_ranks", return_value=None):
            builder.create_new_mappings(df, {})

        auth.generate_access_token.assert_not_called()

    def test_uses_override_search_when_override_name_present(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 1].copy()
        df["override_name"] = ["Aster alpinus"]
        with patch.object(builder, "_search_override", return_value=None) as mock_override:
            with patch.object(builder, "_search_all_ranks") as mock_ranks:
                builder.create_new_mappings(df, {})

        mock_override.assert_called_once_with("Aster alpinus", 1, None)
        mock_ranks.assert_not_called()

    def test_uses_override_search_when_override_map_has_id(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()
        override_map = {2: 999}
        with patch.object(builder, "_search_override", return_value=None) as mock_override:
            with patch.object(builder, "_search_all_ranks") as mock_ranks:
                builder.create_new_mappings(df, override_map)

        mock_override.assert_called_once_with(None, 2, 999)
        mock_ranks.assert_not_called()

    def test_uses_rank_search_when_no_override(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 3].copy()
        with patch.object(builder, "_search_all_ranks", return_value=None) as mock_ranks:
            with patch.object(builder, "_search_override") as mock_override:
                builder.create_new_mappings(df, {})

        mock_ranks.assert_called_once()
        mock_override.assert_not_called()

    def test_matched_taxon_added_to_mappings(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()
        found_taxon = Taxon(taxon_name="Carex stipata", taxon_id=42, est_id=2)
        with patch.object(builder, "_search_all_ranks", return_value=found_taxon):
            result = builder.create_new_mappings(df, {})

        assert len(result) == 1
        assert result.iloc[0]["taxon_id"] == 42
        assert result.iloc[0]["inat_name"] == "Carex stipata"

    def test_no_match_excluded_from_mappings(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()
        with patch.object(builder, "_search_all_ranks", return_value=None):
            result = builder.create_new_mappings(df, {})

        assert len(result) == 0

    def test_process_counters_updated(self, auth, preprocessed_df):
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"].isin([1, 2])].copy()
        with patch.object(builder, "_search_all_ranks", return_value=None):
            builder.create_new_mappings(df, {})

        assert builder.process_total == 2
        assert builder.process_count == 2

    def test_searched_set_shared_across_records(self, auth, preprocessed_df):
        """The same searched_set should be passed to every record's rank search, so
        repeated genus/species lookups across rows are deduplicated."""
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"].isin([1, 2])].copy()
        seen_sets = []

        def fake_search(record, searched_set):
            seen_sets.append(searched_set)
            return None

        with patch.object(builder, "_search_all_ranks", side_effect=fake_search):
            builder.create_new_mappings(df, {})

        assert seen_sets[0] is seen_sets[1]

    def test_too_many_errors_propagates_out_of_create_new_mappings(self, auth, preprocessed_df):
        """Once _make_taxon_request's error threshold is hit, the ValueError should abort
        the whole run rather than being swallowed for just one taxon."""
        builder = TaxonMappingBuilder(auth)
        df = preprocessed_df.loc[preprocessed_df["est_id"] == 2].copy()

        with patch.object(builder, "_search_all_ranks", side_effect=ValueError("Too many errors, aborting search")):
            with pytest.raises(ValueError, match="Too many errors, aborting search"):
                builder.create_new_mappings(df, {})


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
# get_to_match
# ---------------------------------------------------------------------------
class TestGetToMatch:
    def test_raises_on_none_or_empty_tracking_df(self):
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            TaxonMappingBuilder.get_to_match(pd.DataFrame(), None)
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            TaxonMappingBuilder.get_to_match(None, None)
        
    def test_filters_already_mapped_taxa(self, preprocessed_df):
        mapping_df = pd.DataFrame({"est_id": [1, 2]})

        result_df = TaxonMappingBuilder.get_to_match(preprocessed_df, mapping_df)
        
        assert sorted(result_df["est_id"]) == [3, 4]

    def test_returns_none_when_all_already_mapped(self, preprocessed_df):
        mapping_df = pd.DataFrame({"est_id": [1, 2, 3, 4]})
        result = TaxonMappingBuilder.get_to_match(preprocessed_df, mapping_df)
        assert len(result) == 0

    def test_none_mapping_df_maps_all_taxa(self, preprocessed_df):
        result = TaxonMappingBuilder.get_to_match(preprocessed_df, None)
        assert len(result) == 4

    def test_returns_only_needed_columns(self, preprocessed_df):
        mapping_df = pd.DataFrame({"est_id": []})

        result_df = TaxonMappingBuilder.get_to_match(preprocessed_df, mapping_df)

        assert list(result_df.columns) == [
            "sci_name",
            "sci_name_clean",
            "est_id",
            "override_name",
            "is_described",
            "classification_level",
            "parent_egt_id",
            "parent_sci_name",
            "genus_sci_name",
            "genus_egt_id",
        ]