from pathlib import Path
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import sqlite3
import shutil

import pandas as pd
import pytest

from inatdatapipeline import pipeline
from inatdatapipeline.database.db import DBManager
from inatdatapipeline.client.observations import ObservationResults
from inatdatapipeline.client import annotations, taxa
from inatdatapipeline.schemas import config, validation

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "inatdatapipeline" / "schema.sql"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

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
class FakeTaxonMappingBuilder(taxa.TaxonMappingBuilder):
    """
    Subclasses the real TaxonMappingBuilder so every part of the real pipeline runs
    except the actual network call. Only _make_taxon_request is faked, using a small
    canned "API" keyed by search name (for normal/parent/genus searches) or override id
    (for override searches).
    """
    # search_name -> fake API results, same shape the real API returns
    FAKE_RESULTS = {
        "Salix": [{"name": "Salix", "id": 55501, "matched_term": "Salix"}],
        "Festuca rubra": [{"name": "Festuca rubra", "id": 55502, "matched_term": "Festuca rubra"}],
        "Nuphar advena": [{"name": "Nuphar advena", "id": 99999, "matched_term": "Nuphar advena"}]
    }

    # override_id -> fake API results
    FAKE_ID_RESULTS = {
        12345: [{"name": "Carex stipata", "id": 12345, "matched_term": "Carex stipata"}],
        67890: [{"name": "Aster amellus", "id": 67890, "matched_term": "Aster amellus"}],
    }

    def _make_taxon_request(self, search_name, classification_level=None, override_id=None):
        self.request_count += 1
        if override_id:
            return self.FAKE_ID_RESULTS.get(override_id)
        return self.FAKE_RESULTS.get(search_name)

        
class TestTaxa:
    @staticmethod
    def _write_tracking_csv(path: Path):
        pd.DataFrame(
            [
                {
                    "est_id": 101,
                    "egt_id": 5001,
                    "sci_name": "Carex stipata",
                    "global_sci_name": "Carex stipata",
                    "classification_level": "Species",
                    "parent_egt_id": None,
                    "parent_sci_name": None,
                    "element_type": "Plant",
                    "scomname": "owlfruit sedge",
                    "family": "Cyperaceae",
                    "genus_egt_id": 201,
                    "genus": "Carex",
                    "author": "Muhlenberg ex Willdenow",
                    "egt_uid": "EGT-001",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/carex-stipata",
                    "elcode_bcd": "ABNAB",
                    "name_category_desc": "Vascular plant",
                    "growth_habit": "Sedge",
                    "duration": "Perennial",
                },
                {
                    "est_id": 102,
                    "egt_id": 5002,
                    "sci_name": "Aster amellus",
                    "global_sci_name": "Aster amellus",
                    "classification_level": "Species",
                    "parent_egt_id": None,
                    "parent_sci_name": None,
                    "element_type": "Plant",
                    "scomname": "European starwort",
                    "family": "Asteraceae",
                    "genus_egt_id": 202,
                    "genus": "Aster",
                    "author": "L.",
                    "egt_uid": "EGT-002",
                    "s_rank": "S4",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/aster-amellus",
                    "elcode_bcd": "ABNAB",
                    "name_category_desc": "Vascular plant",
                    "growth_habit": "Forb",
                    "duration": "Perennial",
                },
                {
                    "est_id": 103,
                    "egt_id": 5003,
                    "sci_name": "Nuphar advena",
                    "global_sci_name": "Nuphar advena",
                    "classification_level": "Species",
                    "parent_egt_id": None,
                    "parent_sci_name": None,
                    "element_type": "Plant",
                    "scomname": "spadderdock",
                    "family": "Nymphaeaceae",
                    "genus_egt_id": 203,
                    "genus": "Nuphar",
                    "author": "Aiton",
                    "egt_uid": "EGT-003",
                    "s_rank": "S5",
                    "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/nuphar-advena",
                    "elcode_bcd": "ABNAB",
                    "name_category_desc": "Vascular plant",
                    "growth_habit": "Aquatic",
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

        shutil.copy(FIXTURES_DIR / "tracking_scenarios.csv", tracking_file)
        shutil.copy(FIXTURES_DIR / "overrides_scenarios.csv", overrides_file)

        auth = MagicMock()

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

        assert len(tracking_rows) == 6
        assert set(tracking_rows["est_id"]) == {101, 102, 103, 104, 105, 106}

        rel_by_est = rel_rows.set_index("est_id")["taxon_id"].dropna().to_dict() if "est_id" in rel_rows else {}

        # 101/102: override-driven matches
        est_rel = rel_rows.dropna(subset=["est_id"]).set_index("est_id")["taxon_id"].to_dict()
        assert est_rel[101] == 12345
        assert est_rel[102] == 67890

        # 104: undescribed species, matched via genus fallback
        genus_rel = rel_rows.dropna(subset=["genus_egt_id"]).set_index("genus_egt_id")["taxon_id"].to_dict()
        assert genus_rel[204] == 55501

        # 105: undescribed subspecies, matched via parent fallback
        parent_rel = rel_rows.dropna(subset=["parent_egt_id"]).set_index("parent_egt_id")["taxon_id"].to_dict()
        assert parent_rel[5005] == 55502

        # 106: described, no match anywhere - no tracking_rel row references it at all
        assert 106 not in est_rel
        assert 5006 not in parent_rel
        assert 206 not in genus_rel



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


def _make_raw_observation(obs_id: int, taxon_id: int, user_id: int = 1) -> dict:
    """
    Minimal raw iNaturalist observation payload, matching the real API response shape
    that ObservationDownloader._unpack_observation expects (same shape as
    test_observations.py's observation_data fixture).
    """
    return {
        "id": obs_id,
        "uuid": f"uuid-{obs_id}",
        "user": {"id": user_id, "login": f"user{user_id}", "name": f"User {user_id}"},
        "community_taxon_id": taxon_id,
        "license_code": "cc-by",
        "geojson": {"coordinates": [-122.4, 37.8]},
        "private_geojson": {"coordinates": [-122.5234, 37.2339]},
        "positional_accuracy": 10,
        "public_positional_accuracy": 50,
        "observed_on": "2024-03-15",
        "observed_on_string": "March 15, 2024",
        "created_at": "2024-03-16T10:00:00Z",
        "updated_at": "2024-03-17T10:00:00Z",
        "quality_grade": "research",
        "uri": f"https://www.inaturalist.org/observations/{obs_id}",
        "description": "Found near stream",
        "num_identification_agreements": 3,
        "num_identification_disagreements": 0,
        "captive": False,
        "place_guess": "Somewhere",
        "place_guess_private": None,
        "obscured": True,
        "photos": [{"id": 1}],
        "sounds": [],
        "identifications": [],
        "annotations": [],
    }


def _fake_request_batch(observations_by_taxon: dict):
    """
    Returns a drop-in replacement for ObservationDownloader._request_batch that serves
    canned raw observation payloads for whichever taxon ids appear in a given batch, so the
    real fetch_observations/_get_batches/_unpack_results logic runs unmodified. This is the
    only network boundary that gets faked.
    """
    def _request_batch(self, ids, params, headers):
        self.request_count += 1
        results = []
        for taxon_id in ids:
            results.extend(observations_by_taxon.get(taxon_id, []))
        return results
    return _request_batch


class TestObservations:

    @staticmethod
    def _seed_real_mapping(db_manager, rows):
        """
        Seeds tracking_taxa, genera, parent_taxa (as needed), inat_taxa, and tracking_rel
        directly against the real schema, so the real `mappings` view - and therefore the
        real ObservationDownloader.filter_taxa - sees accurate match_type/is_described
        values instead of anything hand-computed by a fake.

        Each row dict needs: est_id, taxon_id, sci_name, common_name, inat_name, elcode,
        growth_habit, is_described, genus_egt_id, and match_level
        ("exact"/"override"/"parent"/"genus", defaults to "exact"). Optional: parent_egt_id,
        parent_sci_name, override_name.
        """
        with db_manager as conn:
            for row in rows:
                match_level = row.get("match_level", "exact")
                parent_egt_id = row.get("parent_egt_id")

                conn._conn.execute(
                    "INSERT OR IGNORE INTO genera (genus_egt_id, genus_sci_name) VALUES (?, ?)",
                    (row["genus_egt_id"], row.get("genus_sci_name", "Test genus")),
                )

                if parent_egt_id is not None:
                    conn._conn.execute(
                        "INSERT OR IGNORE INTO parent_taxa (parent_egt_id, parent_sci_name) VALUES (?, ?)",
                        (parent_egt_id, row.get("parent_sci_name", "Test parent")),
                    )

                override_name = row.get("override_name") or (
                    row["sci_name"] if match_level == "override" else None
                )

                conn._conn.execute(
                    """
                    INSERT INTO tracking_taxa (
                        est_id, egt_id, sci_name, global_sci_name, override_name,
                        classification_level, is_described, parent_egt_id, element_type,
                        common_name, family, genus_egt_id, author, egt_uid, srank,
                        track_status, explorer, elcode, growth_habit, duration
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["est_id"],
                        row.get("egt_id", row["est_id"] + 9000),
                        row["sci_name"],
                        row.get("global_sci_name", row["sci_name"]),
                        override_name,
                        row.get("classification_level", "Species"),
                        row["is_described"],
                        parent_egt_id,
                        "Plant",
                        row["common_name"],
                        "Testaceae",
                        row["genus_egt_id"],
                        "Test Author",
                        "EGT-001",
                        "S5",
                        "Tracked",
                        "https://example.org",
                        row["elcode"],
                        row["growth_habit"],
                        "Perennial",
                    ),
                )

                conn._conn.execute(
                    "INSERT INTO inat_taxa (taxon_id, inat_name) VALUES (?, ?)",
                    (row["taxon_id"], row["inat_name"]),
                )

                # Which of est_id/parent_egt_id/genus_egt_id is populated on tracking_rel
                # drives match_type in the mappings view.
                conn._conn.execute(
                    """
                    INSERT INTO tracking_rel (taxon_id, est_id, parent_egt_id, genus_egt_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        row["taxon_id"],
                        row["est_id"] if match_level in ("exact", "override") else None,
                        parent_egt_id if match_level == "parent" else None,
                        row["genus_egt_id"] if match_level == "genus" else None,
                    ),
                )

            conn._conn.commit()

    def test_get_observations_downloads_and_inserts_results_for_multiple_taxa(self, db_manager, cfg_obs):
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101, "taxon_id": 99, "sci_name": "Test taxon 1",
                    "common_name": "Test plant 1", "inat_name": "Test taxon 1",
                    "elcode": "ABCD123", "growth_habit": "Forb", "is_described": 1,
                    "genus_egt_id": 501, "match_level": "exact",
                },
                {
                    "est_id": 102, "taxon_id": 100, "sci_name": "Test taxon 2",
                    "common_name": "Test plant 2", "inat_name": "Test taxon 2",
                    "elcode": "EFGH456", "growth_habit": "Shrub", "is_described": 1,
                    "genus_egt_id": 502, "match_level": "exact",
                },
            ],
        )

        payloads = {
            99: [_make_raw_observation(1001, taxon_id=99, user_id=1)],
            100: [_make_raw_observation(1002, taxon_id=100, user_id=2)],
        }

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch", _fake_request_batch(payloads)):
                pipeline.get_observations(cfg_obs, db_manager, auth)

        with db_manager as conn:
            obs_rows = conn.select("observations")
            users_rows = conn.select("users")

        assert len(obs_rows) == 2
        assert {1001, 1002} == set(obs_rows["observation_id"])
        assert len(users_rows) == 2

    def test_get_observations_skips_non_exact_matches(self, db_manager, cfg_obs):
        """A parent- or genus-level match (not exact/override) should be filtered out by
        the real filter_taxa before any observations are downloaded at all."""
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101, "taxon_id": 99, "sci_name": "Undescribed taxon",
                    "common_name": "Undescribed plant", "inat_name": "Undescribed taxon",
                    "elcode": "ZZZZ999", "growth_habit": "Forb", "is_described": 0,
                    "genus_egt_id": 503, "match_level": "genus",
                }
            ],
        )

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch") as mock_request:
                pipeline.get_observations(cfg_obs, db_manager, auth)

        mock_request.assert_not_called()

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0

    def test_get_observations_noop_when_no_results_are_returned(self, db_manager, cfg_obs):
        auth = MagicMock()

        self._seed_real_mapping(
            db_manager,
            [
                {
                    "est_id": 101, "taxon_id": 99, "sci_name": "Test taxon",
                    "common_name": "Test plant", "inat_name": "Test taxon",
                    "elcode": "ABCD123", "growth_habit": "Forb", "is_described": 1,
                    "genus_egt_id": 504, "match_level": "exact",
                }
            ],
        )

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch", _fake_request_batch({})):
                pipeline.get_observations(cfg_obs, db_manager, auth)

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0

    def test_get_observations_noop_when_filtered_taxa_are_empty(self, db_manager, cfg_obs):
        """A genus-only mapping row (no tracking_taxa seeded, just inat_taxa/tracking_rel
        via insert_mappings) should be filtered out entirely."""
        auth = MagicMock()

        with db_manager as conn:
            conn.insert_mappings(
                pd.DataFrame(
                    [
                        {
                            "taxon_id": 99,
                            "inat_name": "Test taxon",
                            "est_id": None,
                            "parent_egt_id": None,
                            "genus_egt_id": 505,
                        }
                    ]
                )
            )

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch") as mock_request:
                result = pipeline.get_observations(cfg_obs, db_manager, auth)

        assert result is None
        mock_request.assert_not_called()

        with db_manager as conn:
            obs_rows = conn.select("observations")

        assert len(obs_rows) == 0

    def test_get_observations_noop_when_no_mappings_exist(self, db_manager, cfg_obs):
        auth = MagicMock()

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch") as mock_request:
                result = pipeline.get_observations(cfg_obs, db_manager, auth)

        assert result is None
        mock_request.assert_not_called()

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
                "INSERT INTO genera (genus_egt_id, genus_sci_name) VALUES (?, ?)",
                (601, "Testus"),
            )
            conn._conn.execute(
                """
                INSERT INTO tracking_taxa (
                    est_id, egt_id, sci_name, global_sci_name, override_name,
                    classification_level, is_described, parent_egt_id, element_type,
                    common_name, family, genus_egt_id, author, egt_uid, srank,
                    track_status, explorer, elcode, growth_habit, duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    101, 9101, "Test taxon", "Test taxon", None, "Species", 1, None,
                    "Plant", "Test plant", "Testaceae", 601, "Test Author", "uid_1",
                    "S5", "Tracked", "https://example.org", "ABCD123", "Forb", "Perennial",
                ),
            )

            conn._conn.execute(
                "INSERT INTO inat_taxa (taxon_id, inat_name) VALUES (?, ?)",
                (10, "Test taxon"),
            )

            conn._conn.execute(
                "INSERT INTO tracking_rel (taxon_id, est_id) VALUES (?, ?)",
                (10, 101),
            )
            conn._conn.commit()

        # Seed observations (unchanged)
        raw_result = ObservationResults(
            observations=[
                {
                    "observation_id": 101, "uuid": "uuid-101", "observer_id": 1, "taxon_id": 10,
                    "user_id": 1, "license": "cc-by", "latitude": 44.1, "longitude": -123.2,
                    "latitude_private": None, "longitude_private": None, "coordinate_precision": 20,
                    "coordinate_precision_public": 20, "observed_on": "2024-05-01T12:00:00Z",
                    "observed_on_string": "2024-05-01 12:00", "created_at": "2024-05-01T00:00:00Z",
                    "updated_at": "2024-05-02T00:00:00Z", "quality_grade": "research",
                    "url": "https://example.com/101", "description": "First observation",
                    "id_agreements": 1, "id_disagreements": 0, "captive_cultivated": False,
                    "place_guess": "Portland", "place_guess_private": None, "obscured": False,
                    "has_photo": True, "has_recording": False,
                }
            ],
            identifications=[],
            users=[{"id": 1, "login": "alice", "name": "Alice Example"}],
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
            export_path=str(export_file),
            experts_id_field=validation.EXPERTS_INAT_ID_FIELD,
            experts_expertise_field=validation.EXPERTS_EXPERTISE_FIELD,
            experts_file=str(experts_file),
            export_format=pipeline.EXPORT_FORMAT_CSV
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
                    "est_id": 101, "egt_id": 5001, "sci_name": "Carex stipata",
                    "global_sci_name": "Carex stipata", "classification_level": "Species",
                    "parent_egt_id": None, "parent_sci_name": None, "element_type": "Plant",
                    "scomname": "owlfruit sedge", "family": "Cyperaceae", "genus_egt_id": 201,
                    "genus": "Carex", "author": "Muhlenberg ex Willdenow", "egt_uid": "EGT-001",
                    "s_rank": "S5", "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/carex-stipata",
                    "elcode_bcd": "ABNAB", "name_category_desc": "Vascular plant",
                    "growth_habit": "Sedge", "duration": "Perennial",
                },
                {
                    "est_id": 102, "egt_id": 5002, "sci_name": "Aster amellus",
                    "global_sci_name": "Aster amellus", "classification_level": "Species",
                    "parent_egt_id": None, "parent_sci_name": None, "element_type": "Plant",
                    "scomname": "European starwort", "family": "Asteraceae", "genus_egt_id": 202,
                    "genus": "Aster", "author": "L.", "egt_uid": "EGT-002",
                    "s_rank": "S4", "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/aster-amellus",
                    "elcode_bcd": "ABNAB", "name_category_desc": "Vascular plant",
                    "growth_habit": "Forb", "duration": "Perennial",
                },
                {
                    "est_id": 103, "egt_id": 5003, "sci_name": "Nuphar advena",
                    "global_sci_name": "Nuphar advena", "classification_level": "Species",
                    "parent_egt_id": None, "parent_sci_name": None, "element_type": "Plant",
                    "scomname": "spadderdock", "family": "Nymphaeaceae", "genus_egt_id": 203,
                    "genus": "Nuphar", "author": "Aiton", "egt_uid": "EGT-003",
                    "s_rank": "S5", "eo_track_status_desc": "Tracked",
                    "explorer": "https://example.org/explorer/nuphar-advena",
                    "elcode_bcd": "ABNAB", "name_category_desc": "Vascular plant",
                    "growth_habit": "Aquatic", "duration": "Perennial",
                },
            ]
        ).to_csv(path, index=False)

    @staticmethod
    def _write_overrides_csv(path: Path):
        pd.DataFrame(
            [
                {"est_id": 101, "inat_name": "Carex stipata", "taxon_id": 12345},
                {"est_id": 102, "inat_name": "Aster amellus", "taxon_id": 67890},
            ]
        ).to_csv(path, index=False)

    def test_pipeline_front_to_back(self, tmp_path, db_manager):
        auth = MagicMock()

        # 1) build taxon mapping
        tracking = tmp_path / "tracking.csv"
        overrides = tmp_path / "overrides.csv"

        self._write_tracking_csv(tracking)
        self._write_overrides_csv(overrides)

        with patch.object(pipeline.taxa, "TaxonMappingBuilder", FakeTaxonMappingBuilder):
            pipeline.build_taxon_mapping(str(tracking), str(overrides), db_manager, auth)

        # 2) download observations - est_id 101/102 resolve via override (12345/67890),
        # 103 via FakeTaxonMappingBuilder's "Nuphar advena" entry (99999)
        cfg_obs = config.ObservationsConfig(
            place_id=10,
            quality_grade="research",
            per_page=200,
            batch_size=30,
            update_after_days=7,
            project_id=247148,
            max_observations=10000,
        )

        payloads = {
            12345: [_make_raw_observation(2001, taxon_id=12345, user_id=1)],
            67890: [_make_raw_observation(2002, taxon_id=67890, user_id=1)],
            99999: [_make_raw_observation(2003, taxon_id=99999, user_id=1)],
        }

        with patch.object(pipeline.observations.ObservationDownloader, "_get_fields_rison", return_value="fields"):
            with patch.object(pipeline.observations.ObservationDownloader, "_request_batch", _fake_request_batch(payloads)):
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
            export_path=str(export_csv),
            export_format="CSV File",
        )

        pipeline.run_review(cfg_review, db_manager)

        assert export_csv.exists()
        assert export_csv.stat().st_size > 0