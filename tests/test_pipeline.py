import pytest
import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pandera as pa

from inatdatapipeline.client import (
    taxa,
    review,
    observations
)
from inatdatapipeline.schemas.config import (
    TaxaConfig,
    ReviewConfig,
    ObservationsConfig,
    CoreConfig
)
from inatdatapipeline.schemas import validation
from inatdatapipeline.client import authentication
from inatdatapipeline import (
    db,
    pipeline
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth():
    mock = MagicMock(spec=authentication.INaturalistAuth)
    return mock

@pytest.fixture
def db_manager():
    mock = MagicMock(spec=db.DBManager)
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock

@pytest.fixture
def cfg_taxa():
    return TaxaConfig(
        tracking_list = "data/taxonomy/elcode_tracking_k.csv",
        name_overrides_file = "data/taxonomy/name_overrides.csv",
    )

@pytest.fixture
def cfg_review():
    return ReviewConfig(
        experts_file = "data/experts/Master_iNaturalist_US_Canada_Experts_20240327.csv",
        export_csv = "data/output/observations.csv"
    )

@pytest.fixture
def cfg_obs():
    return ObservationsConfig(
        place_id            = 10,
        quality_grade       = "research",
        per_page            = 200,
        batch_size          = 50,
        fields_json         = "src/inatdatapipeline/obs_fields.json",
        update_after_days   = 0,
        project_id          = 247148,
        max_observations    = 10000,
        timezone            = "America/Los_Angeles"
    )

@pytest.fixture
def mapping_result():
    return pd.DataFrame(
        {
            "est_id":       [1],
            "taxon_id":     [123],
            "inat_name":    ["Carex stipata"],
            "last_updated": [pd.Timestamp("2024-01-01")],
        }
    )



@pytest.fixture(scope="session")
def observation_results(db, auth, obs_cfg):
    mock = MagicMock(spec=observations.ObservationResults)
    return mock


@pytest.fixture
def observation_results_clean():
    mock = MagicMock(spec=observations.ObservationResultsClean)
    mock.to_sqlite.return_value = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# TODO fix these nightmarish nested patches
class TestBuildTaxonMapping:
    def _patch_load(self, tracking_df, overrides_df):
        """Returns a context manager stack that patches CSV loading and schema validation"""
        patches = [
            patch("pandas.read_csv", side_effects=[tracking_df, overrides_df]),
            patch.object(validation.TrackingSchemaClean, "from_raw", return_value=tracking_df),
            patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df),
            patch.object(validation, "OverridesSchema", return_value=overrides_df),
        ]
        return patches
    def test_raises_on_missing_tracking_file(self, cfg_taxa, db_manager, auth):
        with patch("pandas.read_csv", side_effect=FileNotFoundError):
            with pytest.raises(ValueError, match="loading overrides and/or tracking list"):
                pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth)

    def test_raises_on_invalid_tracking_schema(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df):
        with patch("pandas.read_csv", return_value=tracking_df):
            with patch.object(validation.TrackingSchemaClean, "from_raw") as mock_from_raw:
                mock_from_raw.side_effect = pa.errors.SchemaErrors(
                    schema=MagicMock(),
                    data=MagicMock(),
                    schema_errors=[],
                )
                with pytest.raises(ValueError, match="Invalid schema"):
                    pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth)

    def test_loads_existing_mappings_when_not_rebuilding(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df, mapping_result):
        existing_mappings = pd.DataFrame({"est_id": [99]})
        db_manager.select.return_value = existing_mappings

        with patch("pandas.read_csv", side_effect=[tracking_df, overrides_df]):
            with patch.object(validation.TrackingSchemaClean, "from_raw", return_value=tracking_df):
                with patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df):
                    with patch.object(validation, "OverridesSchema", return_value=overrides_df):
                        with patch.object(taxa.TaxonMappingBuilder, "get_new_mappings", return_value=mapping_result):
                            with patch.object(validation.TaxonMappingSchema, "validate", return_value=mapping_result):
                                pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth, rebuild=False)

        db_manager.select.assert_called_once_with("mappings")

    def test_skips_existing_mappings_when_rebuilding(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df, mapping_result):
        with patch("pandas.read_csv", side_effect=[tracking_df, overrides_df]):
            with patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df):
                with patch.object(validation, "OverridesSchema", return_value=overrides_df):
                    with patch.object(taxa.TaxonMappingBuilder, "get_new_mappings", return_value=mapping_result) as mock_build:
                        pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth, rebuild=True)

        # tracking df should be the same as to_match when rebuild is true
        assert len(tracking_df) == len(mock_build.call_args[0][1])

    def test_returns_early_when_no_new_mappings(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df):
        db_manager.select.return_value = pd.DataFrame({"est_id": [1]})

        with patch("pandas.read_csv", side_effect=[tracking_df, overrides_df]):
            with patch.object(validation.TrackingSchemaClean, "from_raw", return_value=tracking_df):
                with patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df):
                    with patch.object(validation, "OverridesSchema", return_value=overrides_df):
                        with patch.object(taxa.TaxonMappingBuilder, "get_new_mappings", return_value=None):
                            # Should not raise and should not attempt db insert
                            pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth)

        db_manager.insert_mappings.assert_not_called()

    def test_raises_on_db_error_loading_mappings(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df):
        db_manager.__enter__.return_value.select.side_effect = sqlite3.Error("db error")

        with patch("pandas.read_csv", side_effect=[tracking_df, overrides_df]):
            with patch.object(validation.TrackingSchemaClean, "from_raw", return_value=tracking_df):
                with patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df):
                    with patch.object(validation, "OverridesSchema", return_value=overrides_df):
                        with pytest.raises(ValueError, match="Failed to load mappings"):
                            pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth, rebuild=False)

    def test_raises_on_db_error_inserting_mappings(self, cfg_taxa, db_manager, auth, tracking_df, overrides_df, mapping_result):
        db_manager.select.return_value = pd.DataFrame({"est_id": []})
        db_manager.__enter__.return_value.insert_mappings.side_effect = sqlite3.Error("insert failed")

        with patch("pandas.read_csv", side_effect=[tracking_df, overrides_df]):
            with patch.object(validation.TrackingSchemaClean, "from_raw", return_value=tracking_df):
                with patch.object(validation, "TrackingSchemaRaw", return_value=tracking_df):
                    with patch.object(validation, "OverridesSchema", return_value=overrides_df):
                        with patch.object(taxa.TaxonMappingBuilder, "get_new_mappings", return_value=mapping_result):
                            with pytest.raises(ValueError, match="Failed to insert mappings"):
                                pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth)



# def test_build_taxon_mapping(tax_cfg, auth: authentication.INaturalistAuth, db: db.DBManager):
#     print("\n\n")
#     print("-------------------------------------------")
#     print("Test run")

#     pipeline.build_taxon_mapping(tax_cfg, db, auth)

#     with db as conn:
#         mapping_df = db.select("mappings")
    
#         if len(mapping_df) == 0:
#             mapping_df = None

#         mappings_count = len(conn.select("mappings"))
#         alt_count = len(conn.select("inat_taxa_alternatives"))
#         print(f"Mappings: {mappings_count}")
#         print(f"Alternative names: {alt_count}")
    
#     print("-------------------------------------------")


# def test_run_review(rev_cfg, all_observations, db, auth):
#     observations = pipeline.run_review(rev_cfg, db, auth)
#     print(observations[observations["identifiedBy"].isna() | observations["identifiedBy"].str.len() == 0])
#     observations.to_csv("data/output/test_observations.csv", index=False)

