from unittest.mock import MagicMock, patch
import logging
import pytest
import datetime
import pandas as pd

from inatdatapipeline.client.taxa import (
    Taxon,
    TaxonMappingBuilder
)
from inatdatapipeline.db import DBManager
from inatdatapipeline.client.authentication import INaturalistAuth

# Set up logging
logger = logging.getLogger('pipeline')

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth():
    mock = MagicMock()
    mock.get_auth_headers.return_value = {"Authorization": "Bearer test_token"}
    return mock



@pytest.fixture
def preprocessed_df(tracking_df):
    """Tracking df with search_name and exact_match already set."""
    df = tracking_df.copy()
    df["search_name"] = ["Aster alpinus", "Carex stipata", "Salix"]
    df["is_described"]    = [True, True, False]
    return df


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
    
    def test_network_error_returns_none(self, auth):
        import requests as req
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("Network error")
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

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
    
    def test_case_insensitive_exact_match(self, auth):
        api_results = [{"id": 123, "name": "carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.taxon_id == 123
    

# ---------------------------------------------------------------------------
# get_new_mappings
# ---------------------------------------------------------------------------

class TestGetNewMappings:
    def test_returns_none_when_no_results(self, preprocessed_df, auth):
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=None):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)
        
        assert result is None

    def test_returns_mapping_result(self, preprocessed_df, auth):
        taxon_results = [
            make_taxon_result(id=i)
            for i in range(len(preprocessed_df))
        ]

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=taxon_results):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df)

        assert result is not None

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
                result = TaxonMappingBuilder.get_new_mappings(auth, preprocessed_df, override_map)

        # The second time query_taxon is called, the third argument should be the override id
        assert mock_query.call_args_list[1].args[2] == 101
        assert mock_query.call_args_list[0].args[2] is None
        assert mock_query.call_args_list[2].args[2] is None


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