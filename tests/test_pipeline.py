from pathlib import Path
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import sqlite3

import pandas as pd
import pytest

from inatdatapipeline import pipeline
from inatdatapipeline.db import DBManager
from inatdatapipeline.client.observations import ObservationResults
from inatdatapipeline.client import annotations
from inatdatapipeline.schemas import config, validation

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "inatdatapipeline" / "schema.sql"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "taxa_integration.gpkg"
    manager = DBManager(str(db_path))
    manager.connect()
    manager.setup_db(str(SCHEMA_SQL))
    yield manager
    if manager._conn is not None:
        manager._conn.close()


# ---------------------------------------------------------------------------
# Taxa
# ---------------------------------------------------------------------------
class FakeTaxonMappingBuilder:
    def __init__(self, tracking_df, overrides_df, auth):
        self.tracking_df = tracking_df
        self.overrides_df = overrides_df
        self.auth = auth

    @staticmethod
    def preprocess_tracking_df(tracking_df, overrides_df):
        df = tracking_df.copy()
        df["search_name"] = df["sci_name"]
        df["is_described"] = True
        return df

    @staticmethod
    def build_override_id_map(overrides_df):
        if overrides_df is None or overrides_df.empty:
            return {}
        return dict(zip(overrides_df["est_id"], overrides_df["taxon_id"]))

    @staticmethod
    def get_to_match(tracking_df, mapping_df):
        needed_cols = ["est_id", "sci_name", "search_name", "is_described"]
        if mapping_df is None or mapping_df.empty:
            return tracking_df[needed_cols].copy()

        # 103 is already mapped; 101 and 102 are new mappings.
        mask = ~tracking_df["est_id"].isin(mapping_df["est_id"])
        return tracking_df.loc[mask, needed_cols].copy()

    @staticmethod
    def get_new_mappings(auth, to_match, override_map=None):
        if override_map is None:
            override_map = {}

        rows = []
        for _, row in to_match.iterrows():
            est_id = int(row["est_id"])
            override_id = override_map.get(est_id)  # optional only; may be None

            # Simulate the real function: if override exists, use it as API search target;
            # otherwise query by scientific name.
            taxon_name = row["sci_name"]

            rows.append(
                {
                    "est_id": est_id,
                    "taxon_id": override_id if override_id is not None else 99999,
                    "inat_name": taxon_name,
                }
            )

        return pd.DataFrame(rows), len(rows)

        
class TestTaxa:

    @staticmethod
    def _write_tracking_csv(path: Path):
        pd.DataFrame(
            [
                {
                    "name": 101,
                    "sname": "Carex stipata",
                    "author": "Muhlenberg ex Willdenow",
                    "scomname": "owlfruit sedge",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/carex-stipata",
                    "egt_uid": "EGT-001",
                    "family": "Cyperaceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Sedge",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
                {
                    "name": 102,
                    "sname": "Aster amellus",
                    "author": "L.",
                    "scomname": "European starwort",
                    "s_rank": "S4",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/aster-amellus",
                    "egt_uid": "EGT-002",
                    "family": "Asteraceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Forb",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
                {
                    "name": 103,
                    "sname": "Nuphar advena",
                    "author": "Aiton",
                    "scomname": "spadderdock",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/nuphar-advena",
                    "egt_uid": "EGT-003",
                    "family": "Nymphaeaceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Aquatic",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
            ]
        ).to_csv(path, index=False)


    @staticmethod
    def _write_overrides_csv(path: Path):
        pd.DataFrame(
            [
                {
                    "est_id": 101,
                    "inat_name": "Carex stipata",
                    "taxon_id": 12345,
                },
                {
                    "est_id": 102,
                    "inat_name": "Aster amellus",
                    "taxon_id": 67890,
                },
            ]
        ).to_csv(path, index=False)


    def test_build_taxon_mapping_end_to_end_with_patched_api(self, db_manager, tmp_path):
        tracking_file = tmp_path / "tracking.csv"
        overrides_file = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking_file)
        self._write_overrides_csv(overrides_file)

        auth = MagicMock()
        
        with db_manager as conn:
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (99999, "Nuphar advena"),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (103, 99999),
            )
            conn._conn.commit()

        with patch.object(pipeline.taxa, "TaxonMappingBuilder", FakeTaxonMappingBuilder):
            pipeline.build_taxon_mapping(
                str(tracking_file),
                str(overrides_file),
                db_manager,
                auth,
                rebuild=True,
            )

        with db_manager as conn:
            tracking_rows = conn.select("tracking_taxa")
            rel_rows = conn.select("tracking_rel")
            inat_rows = conn.select("inat_taxa")

        assert len(tracking_rows) == 3
        assert set(tracking_rows["est_id"]) == {101, 102, 103}

        rel_by_est = rel_rows.set_index("est_id")["taxon_id"].to_dict()
        assert rel_by_est[101] == 12345
        assert rel_by_est[102] == 67890
        assert rel_by_est[103] == 99999

        inat_names = set(inat_rows["inat_name"])
        assert "Carex stipata" in inat_names
        assert "Aster amellus" in inat_names
        assert "Nuphar advena" in inat_names



    def test_build_taxon_mapping_skips_existing_mappings_when_rebuild_is_false(self, db_manager, tmp_path):
        tracking_file = tmp_path / "tracking.csv"
        overrides_file = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking_file)
        self._write_overrides_csv(overrides_file)

        auth = MagicMock()

        # Seed an existing mapping so build_taxon_mapping() should skip it.
        with db_manager as conn:
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (99999, "Nuphar advena"),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (103, 99999),
            )
            conn._conn.commit()

        with patch.object(pipeline.taxa, "TaxonMappingBuilder", FakeTaxonMappingBuilder):
            pipeline.build_taxon_mapping(
                str(tracking_file),
                str(overrides_file),
                db_manager,
                auth,
                rebuild=False,
            )

        with db_manager as conn:
            rel_rows = conn.select("tracking_rel")

        rel_by_est = rel_rows.set_index("est_id")["taxon_id"].to_dict()

        assert rel_by_est[103] == 99999
        assert 101 in rel_by_est
        assert 102 in rel_by_est


    def test_build_taxon_mapping_rebuild_true_remaps_all_rows(self, db_manager, tmp_path):
        tracking_file = tmp_path / "tracking.csv"
        overrides_file = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking_file)
        self._write_overrides_csv(overrides_file)

        auth = MagicMock()

        # Seed some stale mapping values.
        with db_manager as conn:
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (11111, "Old taxon"),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (101, 11111),
            )
            conn._conn.commit()

        with patch.object(pipeline.taxa, "TaxonMappingBuilder", FakeTaxonMappingBuilder):
            pipeline.build_taxon_mapping(
                str(tracking_file),
                str(overrides_file),
                db_manager,
                auth,
                rebuild=True,
            )

        with db_manager as conn:
            rel_rows = conn.select("tracking_rel")

        rel_by_est = rel_rows.set_index("est_id")["taxon_id"].to_dict()
        assert rel_by_est[101] == 12345
        assert rel_by_est[102] == 67890
        assert rel_by_est[103] == 99999


    def test_build_taxon_mapping_noop_when_everything_is_already_mapped(self, db_manager, tmp_path):
        tracking_file = tmp_path / "tracking.csv"
        overrides_file = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking_file)
        self._write_overrides_csv(overrides_file)

        auth = MagicMock()

        with db_manager as conn:
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (12345, "Carex stipata"),
            )
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (67890, "Aster amellus"),
            )
            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (99999, "Nuphar advena"),
            )

            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (101, 12345),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (102, 67890),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_rel (est_id, taxon_id)
                VALUES (?, ?)
                """,
                (103, 99999),
            )
            conn._conn.commit()

        with patch.object(pipeline.taxa, "TaxonMappingBuilder", FakeTaxonMappingBuilder):
            pipeline.build_taxon_mapping(
                str(tracking_file),
                str(overrides_file),
                db_manager,
                auth,
                rebuild=False,
            )

        with db_manager as conn:
            rel_rows = conn.select("tracking_rel")

        assert len(rel_rows) == 3
        assert set(rel_rows["est_id"]) == {101, 102, 103}

    ### Negative cases ###
    def test_build_taxon_mapping_raises_value_error_for_invalid_tracking_csv(self, db_manager, tmp_path):
        tracking_file = tmp_path / "bad_tracking.csv"
        overrides_file = tmp_path / "overrides.csv"

        pd.DataFrame([{"not_a_valid_tracking_column": "Carex stipata"}]).to_csv(tracking_file, index=False)
        pd.DataFrame([{"est_id": 101, "inat_name": "Carex stipata", "taxon_id": 12345}]).to_csv(
            overrides_file, index=False
        )

        auth = MagicMock()

        with pytest.raises(ValueError, match="tracking|validation|schema|failed"):
            pipeline.build_taxon_mapping(
                str(tracking_file),
                str(overrides_file),
                db_manager,
                auth,
                rebuild=False,
            )


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------
@pytest.fixture
def cfg_obs():
    return config.ObservationsConfig(
        place_id=10,
        quality_grade="research",
        per_page=200,
        batch_size=30,
        update_after_days=7,
        max_observations=10000,
        project_id=247148,
    )



class FakeDownloader:
    def __init__(self, cfg, auth):
        self.config = cfg
        self.auth = auth

        self.total_taxa_count = 0
        self.filtered_taxa_count = 0
        self.undescribed_taxa_count = 0

        self.request_count = 3
        self.taxa_completed = 0
        self.exceeded_download_max = False
        self.taxa_remaining = 0

    def filter_taxa(self, taxa_df):
        df = taxa_df.copy()
        df = df[df["is_described"] == 1]
        self.total_taxa_count = len(taxa_df)
        self.undescribed_taxa_count = len(taxa_df) - len(df)
        self.filtered_taxa_count = len(df)
        return df

    def fetch_observations(self, taxa_df):
        self.taxa_completed = len(taxa_df)
        self.taxa_remaining = 0

        taxon_id = int(taxa_df.iloc[0]["taxon_id"])

        return ObservationResults(
            observations=[
                {
                    "observation_id": 1001,
                    "uuid": "uuid-1001",
                    "observer_id": 1,
                    "taxon_id": taxon_id,
                    "user_id": 1,
                    "license": "cc-by",
                    "latitude": 37.8,
                    "longitude": -122.4,
                    "latitude_private": 37.2339,
                    "longitude_private": -122.5234,
                    "coordinate_precision": 10,
                    "coordinate_precision_public": 50,
                    "observed_on": "2024-03-15T00:00:00Z",
                    "observed_on_string": "March 15, 2024",
                    "created_at": "2024-03-16T10:00:00Z",
                    "updated_at": "2024-03-17T10:00:00Z",
                    "quality_grade": "research",
                    "url": "https://www.inaturalist.org/observations/1001",
                    "description": "Found near stream",
                    "id_agreements": 3,
                    "id_disagreements": 0,
                    "captive_cultivated": False,
                    "place_guess": "Somewhere",
                    "place_guess_private": None,
                    "obscured": True,
                    "has_photo": True,
                    "has_recording": False,
                },
                {
                    "observation_id": 1002,
                    "uuid": "uuid-1002",
                    "observer_id": 2,
                    "taxon_id": 100,
                    "user_id": 2,
                    "license": "cc-by",
                    "latitude": 38.0,
                    "longitude": -122.3,
                    "latitude_private": 38.1,
                    "longitude_private": -122.4,
                    "coordinate_precision": 12,
                    "coordinate_precision_public": 60,
                    "observed_on": "2024-03-18T00:00:00Z",
                    "observed_on_string": "March 18, 2024",
                    "created_at": "2024-03-19T10:00:00Z",
                    "updated_at": "2024-03-20T10:00:00Z",
                    "quality_grade": "research",
                    "url": "https://www.inaturalist.org/observations/1002",
                    "description": "Second sample",
                    "id_agreements": 2,
                    "id_disagreements": 0,
                    "captive_cultivated": False,
                    "place_guess": "Elsewhere",
                    "place_guess_private": None,
                    "obscured": False,
                    "has_photo": True,
                    "has_recording": False,
                },
            ],
            identifications=[
                {
                    "identification_id": 5,
                    "observation_id": 1001,
                    "user_id": 1,
                    "taxon_id": 99,
                    "created_at": "2024-03-16T12:00:00Z",
                }
            ],
            users=[
                {"id": 1, "login": "user1", "name": "User One"},
                {"id": 2, "login": "user2", "name": "User Two"},
            ],
            annotations=[],
            completed_taxa={99, 100},
        )


class EmptyTaxaDownloader(FakeDownloader):
    def filter_taxa(self, taxa_df):
        self.total_taxa_count = len(taxa_df)
        self.undescribed_taxa_count = len(taxa_df)
        self.filtered_taxa_count = 0
        return taxa_df.iloc[0:0]
        

class TestObservations:
    
    @staticmethod
    def _seed_real_mapping(db_manager, rows):
        with db_manager as conn:
            for row in rows:
                conn._conn.execute(
                    """
                    INSERT INTO tracking_taxa (
                        est_id, sci_name, search_name, is_described,
                        element_type, scientific_name, common_name, element_name,
                        family, author, egt_uid, srank, track_status,
                        explorer, explorer_link, elcode, growth_habit, duration
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["est_id"],
                        row["sci_name"],
                        row["search_name"],
                        row["is_described"],
                        "Plant",
                        row["sci_name"],
                        row["common_name"],
                        row["sci_name"],
                        "Testaceae",
                        "Test Author",
                        "EGT-001",
                        "S5",
                        "Tracked",
                        "https://example.org",
                        "https://example.org",
                        row["elcode"],
                        row["growth_habit"],
                        "Perennial",
                    ),
                )

                conn._conn.execute(
                    """
                    INSERT INTO inat_taxa (taxon_id, inat_name)
                    VALUES (?, ?)
                    """,
                    (row["taxon_id"], row["inat_name"]),
                )

                conn._conn.execute(
                    """
                    INSERT INTO tracking_rel (est_id, taxon_id)
                    VALUES (?, ?)
                    """,
                    (row["est_id"], row["taxon_id"]),
                )

            conn._conn.commit()
    
    def test_get_observations_downloads_and_inserts_results_for_multiple_taxa(self, db_manager, cfg_obs):
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101,
                    "taxon_id": 99,
                    "sci_name": "Test taxon 1",
                    "search_name": "Test taxon 1",
                    "common_name": "Test plant 1",
                    "inat_name": "Test taxon 1",
                    "elcode": "ABCD123",
                    "growth_habit": "Forb",
                    "is_described": 1,
                },
                {
                    "est_id": 102,
                    "taxon_id": 100,
                    "sci_name": "Test taxon 2",
                    "search_name": "Test taxon 2",
                    "common_name": "Test plant 2",
                    "inat_name": "Test taxon 2",
                    "elcode": "EFGH456",
                    "growth_habit": "Shrub",
                    "is_described": 1,
                },
            ],
        )

        with patch.object(pipeline.observations, "ObservationDownloader", FakeDownloader):
            pipeline.get_observations(cfg_obs, db_manager, auth)

        with db_manager as conn:
            obs_rows = conn.select("observations")
            users_rows = conn.select("users")

        assert len(obs_rows) == 2
        assert {1001, 1002} == set(obs_rows["observation_id"])
        assert len(users_rows) == 2

    def test_get_observations_skips_undescribed_taxa(self, db_manager, cfg_obs):
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101,
                    "taxon_id": 99,
                    "sci_name": "Undescribed taxon",
                    "search_name": "Undescribed taxon",
                    "common_name": "Undescribed plant",
                    "inat_name": "Undescribed taxon",
                    "elcode": "ZZZZ999",
                    "growth_habit": "Forb",
                    "is_described": 0,
                }
            ],
        )

        with patch.object(pipeline.observations, "ObservationDownloader", EmptyTaxaDownloader):
            pipeline.get_observations(cfg_obs, db_manager, auth)

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0

    def test_get_observations_noop_when_no_results_are_returned(self, db_manager, cfg_obs):
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101,
                    "taxon_id": 99,
                    "sci_name": "Test taxon",
                    "search_name": "Test taxon",
                    "common_name": "Test plant",
                    "inat_name": "Test taxon",
                    "elcode": "ABCD123",
                    "growth_habit": "Forb",
                    "is_described": 1,
                }
            ],
        )

        with patch.object(pipeline.observations, "ObservationDownloader", EmptyTaxaDownloader):
            pipeline.get_observations(cfg_obs, db_manager, auth)

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0

    def test_get_observations_noop_when_filtered_taxa_are_empty(self, db_manager, cfg_obs):
        auth = MagicMock()

        with db_manager as conn:
            conn.insert_mappings(
                pd.DataFrame(
                    [
                        {
                            "est_id": 101,
                            "taxon_id": 99,
                            "inat_name": "Test taxon",
                            "sci_name": "Test taxon",
                            "search_name": "Test taxon",
                            "is_described": 0,
                            "date_updated": None,
                        }
                    ]
                )
            )

        with patch.object(pipeline.observations, "ObservationDownloader", EmptyTaxaDownloader):
            result = pipeline.get_observations(cfg_obs, db_manager, auth)

        assert result is None

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0


    def test_get_observations_noop_when_no_mappings_exist(self, db_manager, cfg_obs):
        auth = MagicMock()

        with patch.object(pipeline.observations, "ObservationDownloader", FakeDownloader):
            result = pipeline.get_observations(cfg_obs, db_manager, auth)

        assert result is None

        with db_manager as conn:
            obs_rows = conn.select("observations")
            mappings_rows = conn.select("mappings")

        assert len(mappings_rows) == 0
        assert len(obs_rows) == 0


# ---------------------------------------------------------------------------
# Update Annotations
# ---------------------------------------------------------------------------
class TestUpdateAnnotations:

    class FakeAnnotationOptions:
        def __init__(self):
            self.categories = [
                {"annotation_id": 1, "label": "Life Stage"},
                {"annotation_id": 2, "label": "Plant Phenology"},
            ]
            self.values = [
                {"value_id": 1, "annotation_id": 1, "label": "Adult"},
                {"value_id": 2, "annotation_id": 1, "label": "Juvenile"},
                {"value_id": 3, "annotation_id": 2, "label": "Flowering"},
                {"value_id": 4, "annotation_id": 2, "label": "Fruiting"},
            ]


    def test_update_annotations_inserts_annotation_options(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.annotations,
            "fetch_annotations",
            return_value=self.FakeAnnotationOptions(),
        ):
            pipeline.update_annotations(db_manager, auth)

        with db_manager as conn:
            options = conn.select("annotation_options")
            values = conn.select("annotation_values")

        assert len(options) >= 2
        assert len(values) >= 4
        assert {row["label"] for _, row in options.iterrows()} >= {"Life Stage", "Plant Phenology"}
    
    def test_update_annotations_raises_value_error_on_network_error(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.annotations,
            "fetch_annotations",
            side_effect=ValueError("network failure"),
        ):
            with pytest.raises(ValueError, match="Network exception occurred while requesting annotations"):
                pipeline.update_annotations(db_manager, auth)

    def test_update_annotations_raises_value_error_on_db_error(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.annotations,
            "fetch_annotations",
            return_value=TestUpdateAnnotations.FakeAnnotationOptions(),
        ):
            with patch.object(
                DBManager,
                "update_annotations",
                side_effect=sqlite3.Error("db failure"),
            ):
                with pytest.raises(ValueError, match="Database exception occurred while updating annotations"):
                    pipeline.update_annotations(db_manager, auth)
    

# ---------------------------------------------------------------------------
# Update Project Members
# ---------------------------------------------------------------------------
class TestUpdateProjectMembers:
    def test_update_project_members_inserts_member_ids(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.helpers,
            "fetch_project_members",
            return_value=[101, 102, 103],
        ):
            pipeline.update_project_members(247148, db_manager, auth)

        with db_manager as conn:
            rows = conn.select("project_members")

        assert sorted(rows["user_id"].tolist()) == [101, 102, 103]
    
    def test_update_project_members_propagates_fetch_error(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.helpers,
            "fetch_project_members",
            side_effect=ValueError("network failure"),
        ):
            with pytest.raises(ValueError, match="network failure"):
                pipeline.update_project_members(247148, db_manager, auth)

    def test_update_project_members_raises_value_error_on_db_error(self, db_manager):
        auth = MagicMock()

        with patch.object(
            pipeline.helpers,
            "fetch_project_members",
            return_value=[101, 102, 103],
        ):
            with patch.object(
                DBManager,
                "replace_project_members",
                side_effect=sqlite3.Error("db failure"),
            ):
                with pytest.raises(ValueError):
                    pipeline.update_project_members(247148, db_manager, auth)


class TestReview:
    @staticmethod
    def _seed_review_inputs(db_manager: DBManager):
        # Update project members
        with db_manager as conn:
            conn.replace_project_members([1, 2])

        # Update annotation options
        ann_opts = annotations.AnnotationOptions(
            categories=[
                {"annotation_id": 1, "label": "Life Stage"},
                {"annotation_id": 2, "label": "Phenology"},
            ],
            values=[
                {"value_id": 1, "annotation_id": 1, "label": "Adult"},
                {"value_id": 2, "annotation_id": 2, "label": "Flowering"},
            ],
        )
        with db_manager as conn:
            conn.update_annotations(ann_opts)

        # Insert taxa
        with db_manager as conn:
            conn._conn.execute(
                """
                INSERT INTO tracking_taxa (
                    est_id, sci_name, search_name, is_described,
                    element_type, scientific_name, common_name, element_name,
                    family, author, egt_uid, srank, track_status,
                    explorer, explorer_link, elcode, growth_habit, duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    101,
                    "Test taxon",
                    "Test taxon",
                    1,
                    "Plant",
                    "Test taxon",
                    "Test plant",
                    "Test taxon",
                    "Testaceae",
                    "Test Author",
                    "uid_1",
                    "S5",
                    "Tracked",
                    "https://example.org",
                    "https://example.org",
                    "ABCD123",
                    "Forb",
                    "Perennial",
                ),
            )

            conn._conn.execute(
                """
                INSERT INTO inat_taxa (taxon_id, inat_name)
                VALUES (?, ?)
                """,
                (10, "Test taxon"),
            )

            conn._conn.execute(
                """
                INSERT INTO tracking_rel (taxon_id, est_id)
                VALUES (?, ?)
                """,
                (10, 101),
            )
            conn._conn.commit()

        # Seed observations
        raw_result = ObservationResults(
            observations=[
                {
                    "observation_id": 101,
                    "uuid": "uuid-101",
                    "observer_id": 1,
                    "taxon_id": 10,
                    "user_id": 1,
                    "license": "cc-by",
                    "latitude": 44.1,
                    "longitude": -123.2,
                    "latitude_private": None,
                    "longitude_private": None,
                    "coordinate_precision": 20,
                    "coordinate_precision_public": 20,
                    "observed_on": "2024-05-01T12:00:00Z",
                    "observed_on_string": "2024-05-01 12:00",
                    "created_at": "2024-05-01T00:00:00Z",
                    "updated_at": "2024-05-02T00:00:00Z",
                    "quality_grade": "research",
                    "url": "https://example.com/101",
                    "description": "First observation",
                    "id_agreements": 1,
                    "id_disagreements": 0,
                    "captive_cultivated": False,
                    "place_guess": "Portland",
                    "place_guess_private": None,
                    "obscured": False,
                    "has_photo": True,
                    "has_recording": False,
                }
            ],
            identifications=[],
            users=[
                {"id": 1, "login": "alice", "name": "Alice Example"}
            ],
            annotations=[],
            completed_taxa={10},
        )

        validated = pipeline.observations.ObservationResultsValidator.validate(raw_result)
        db_manager.insert_observation_results(validated.to_sqlite())


    def test_update_experts_inserts_rows(self, db_manager, tmp_path):
        experts_file = tmp_path / "experts.csv"

        pd.DataFrame(
            [
                {
                    validation.EXPERTS_INAT_ID_FIELD: 1001,
                    validation.EXPERTS_EXPERTISE_FIELD: "Plant",
                },
                {
                    validation.EXPERTS_INAT_ID_FIELD: 1002,
                    validation.EXPERTS_EXPERTISE_FIELD: "Plant",
                },
            ]
        ).to_csv(experts_file, index=False)

        df = pipeline.update_experts(
            str(experts_file),
            validation.EXPERTS_INAT_ID_FIELD,
            validation.EXPERTS_EXPERTISE_FIELD,
            db_manager
        )

        assert len(df) == 2
        assert set(df["user_id"]) == {1001, 1002}


    def test_get_data_loads_valid_review_inputs(self, db_manager):
        self._seed_review_inputs(db_manager)

        project_members, expert_ids_df, observations_df, annotations_df = pipeline._get_data(db_manager)

        assert project_members == {1, 2}
        assert len(observations_df) == 1
        assert len(annotations_df) == 0 or "observation_id" in annotations_df.columns
        assert "observation_id" in expert_ids_df.columns or len(expert_ids_df) == 0


    def test_run_review_exports_reviewed_csv(self, db_manager, tmp_path):
        self._seed_review_inputs(db_manager)

        experts_file = tmp_path / "experts.csv"
        export_file = tmp_path / "reviewed.csv"

        pd.DataFrame(
            [
                {
                    validation.EXPERTS_INAT_ID_FIELD: 1001,
                    validation.EXPERTS_EXPERTISE_FIELD: "Plant",
                }
            ]
        ).to_csv(experts_file, index=False)

        cfg_review = config.ReviewConfig(
            export_csv=str(export_file),
            experts_id_field=validation.EXPERTS_INAT_ID_FIELD,
            experts_expertise_field=validation.EXPERTS_EXPERTISE_FIELD,
            experts_file=str(experts_file),
        )

        pipeline.run_review(cfg_review, db_manager)

        assert export_file.exists()
        export_df = pd.read_csv(export_file)

        assert len(export_df) >= 1
        assert "catalogNumber" in export_df.columns
        assert "expert_verified" in export_df.columns
        assert "annotations" in export_df.columns



class TestFullPipeline:
    @staticmethod
    def _write_tracking_csv(path: Path):
        pd.DataFrame(
            [
                {
                    "name": 101,
                    "sname": "Carex stipata",
                    "author": "Muhlenberg ex Willdenow",
                    "scomname": "owlfruit sedge",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/carex-stipata",
                    "egt_uid": "EGT-001",
                    "family": "Cyperaceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Sedge",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
                {
                    "name": 102,
                    "sname": "Aster amellus",
                    "author": "L.",
                    "scomname": "European starwort",
                    "s_rank": "S4",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/aster-amellus",
                    "egt_uid": "EGT-002",
                    "family": "Asteraceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Forb",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
                {
                    "name": 103,
                    "sname": "Nuphar advena",
                    "author": "Aiton",
                    "scomname": "spadderdock",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/nuphar-advena",
                    "egt_uid": "EGT-003",
                    "family": "Nymphaeaceae",
                    "ELCODE_BCD": "ABNAB",
                    "NAME_CATEGORY_DESC": "Vascular plant",
                    "growth_habit": "Aquatic",
                    "element_type": "Plant",
                    "duration": "Perennial",
                },
            ]
        ).to_csv(path, index=False)


    @staticmethod
    def _write_overrides_csv(path: Path):
        pd.DataFrame(
            [
                {
                    "est_id": 101,
                    "inat_name": "Carex stipata",
                    "taxon_id": 12345,
                },
                {
                    "est_id": 102,
                    "inat_name": "Aster amellus",
                    "taxon_id": 67890,
                },
            ]
        ).to_csv(path, index=False)

    def test_pipeline_front_to_back(self, tmp_path, db_manager):
        auth = MagicMock()

        # 1) build taxon mapping
        tracking = tmp_path / "tracking.csv"
        overrides = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking)
        self._write_overrides_csv(overrides)

        pipeline.build_taxon_mapping(str(tracking), str(overrides), db_manager, auth)

        cfg_obs = config.ObservationsConfig(
            place_id=10,
            quality_grade="research",
            per_page=200,
            batch_size=30,
            update_after_days=7,
            project_id=247148,
            max_observations=10000,
        )

        with patch("inatdatapipeline.pipeline.observations.ObservationDownloader", FakeDownloader):
            pipeline.get_observations(cfg_obs, db_manager, auth)

        # 3) project members + annotations + review
        with patch("inatdatapipeline.pipeline.helpers.fetch_project_members", return_value=[1]):
            pipeline.update_project_members(247148, db_manager, auth)

        ann_opts = annotations.AnnotationOptions(
            categories=[{"annotation_id": 1, "label": "Life Stage"}],
            values=[{"value_id": 1, "annotation_id": 1, "label": "Adult"}],
        )

        with patch("inatdatapipeline.pipeline.annotations.fetch_annotations", return_value=ann_opts):
            pipeline.update_annotations(db_manager, auth)

        experts_file = tmp_path / "experts.csv"
        pd.DataFrame(
            [{
                validation.EXPERTS_INAT_ID_FIELD: 1001, 
                validation.EXPERTS_EXPERTISE_FIELD: "Plant"
            }]
        ).to_csv(experts_file, index=False)

        export_csv = tmp_path / "reviewed.csv"
        cfg_review = config.ReviewConfig(
            experts_file=str(experts_file),
            experts_id_field=validation.EXPERTS_INAT_ID_FIELD,
            experts_expertise_field=validation.EXPERTS_EXPERTISE_FIELD,
            export_csv=str(export_csv),
        )

        pipeline.run_review(cfg_review, db_manager)

        with open(export_csv, "r") as fp:
            while (line := fp.readline()):
                print(line)

        assert export_csv.exists()
        assert export_csv.stat().st_size > 0