import pandas as pd
import numpy as np
import pytest

from inatdatapipeline.client.review import Reviewer
from inatdatapipeline import schemas
from inatdatapipeline.config import ReviewConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def observations_df() -> pd.DataFrame:
    """Return a small but schema-complete observation dataframe."""
    data = [
        {
            "observation_id": 101,
            "uuid": "uuid-101",
            "observer_id": 1,
            "taxon_id": 10,
            "license": "cc-by",
            "latitude": 44.1,
            "longitude": -123.2,
            "latitude_private": None,
            "longitude_private": None,
            "coordinate_precision": 20,
            "coordinate_precision_public": 20,
            "observed_on_string": "2024-05-01 12:00",
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
            "observed_on": pd.Timestamp("2024-05-01"),
            "created_at": pd.Timestamp("2024-05-01 00:00:00"),
            "updated_at": pd.Timestamp("2024-05-02 00:00:00"),
            "est_id": 123,
            "sci_name": "Aster amellus",
            "search_name": "Aster amellus",
            "is_described": True,
            "element_type": "Plant",
            "scientific_name": "<i>Aster amellus</i>",
            "common_name": "European starwort",
            "element_name": "123",
            "family": "Asteraceae",
            "author": "L.",
            "egt_uid": "egt-123",
            "srank": "S4",
            "track_status": "Tracked",
            "explorer": "https://explorer.example/123",
            "explorer_link": "<a href=\"https://explorer.example/123\">View in Explorer</a>",
            "elcode": "ABC123",
            "growth_habit": "Forb",
            "duration": "Perennial",
            "name": "Alice Example",
            "login": "alice",
        },
        {
            "observation_id": 102,
            "uuid": "uuid-102",
            "observer_id": 2,
            "taxon_id": 11,
            "license": "cc0",
            "latitude": 44.2,
            "longitude": -123.3,
            "latitude_private": None,
            "longitude_private": None,
            "coordinate_precision": 10,
            "coordinate_precision_public": 10,
            "observed_on_string": "2024-05-03 09:00",
            "quality_grade": "research",
            "url": "https://example.com/102",
            "description": "Second observation",
            "id_agreements": 1,
            "id_disagreements": 1,
            "captive_cultivated": False,
            "place_guess": "Eugene",
            "place_guess_private": None,
            "obscured": False,
            "has_photo": False,
            "has_recording": True,
            "observed_on": pd.Timestamp("2024-05-03"),
            "created_at": pd.Timestamp("2024-05-03 00:00:00"),
            "updated_at": pd.Timestamp("2024-05-04 00:00:00"),
            "est_id": 124,
            "sci_name": "Castilleja miniata",
            "search_name": "Castilleja miniata",
            "is_described": True,
            "element_type": "Plant",
            "scientific_name": "<i>Castilleja miniata</i>",
            "common_name": "Greater paintbrush",
            "element_name": "124",
            "family": "Orobanchaceae",
            "author": "Douglas ex Hook.",
            "egt_uid": "egt-124",
            "srank": "S5",
            "track_status": "Tracked",
            "explorer": "https://explorer.example/124",
            "explorer_link": "<a href=\"https://explorer.example/124\">View in Explorer</a>",
            "elcode": "XYZ456",
            "growth_habit": "Forb",
            "duration": "Perennial",
            "name": "Bob Example",
            "login": "bobj",
        },
        {
            "observation_id": 103,
            "uuid": "uuid-103",
            "observer_id": 3,
            "taxon_id": 12,
            "license": "cc-by-nc",
            "latitude": 44.3,
            "longitude": -123.4,
            "latitude_private": 44.2335,
            "longitude_private": -123.4352,
            "coordinate_precision": 30,
            "coordinate_precision_public": 30,
            "observed_on_string": "2024-05-07 17:00",
            "quality_grade": "research",
            "url": "https://example.com/103",
            "description": "Third observation",
            "id_agreements": 0,
            "id_disagreements": 0,
            "captive_cultivated": False,
            "place_guess": None,
            "place_guess_private": "Salem",
            "obscured": True,
            "has_photo": True,
            "has_recording": True,
            "observed_on": pd.Timestamp("2024-05-07"),
            "created_at": pd.Timestamp("2024-05-07 00:00:00"),
            "updated_at": pd.Timestamp("2024-05-08 00:00:00"),
            "est_id": 125,
            "sci_name": "Lupinus arboreus",
            "search_name": "Lupinus arboreus",
            "is_described": True,
            "element_type": "Plant",
            "scientific_name": "<i>Lupinus arboreus</i>",
            "common_name": "Tree lupine",
            "element_name": "125",
            "family": "Fabaceae",
            "author": "Sims",
            "egt_uid": "egt-125",
            "srank": "S4",
            "track_status": "Tracked",
            "explorer": "https://explorer.example/125",
            "explorer_link": "<a href=\"https://explorer.example/125\">View in Explorer</a>",
            "elcode": "LMN789",
            "growth_habit": "Shrub",
            "duration": "Perennial",
            "name": "Carol Example",
            "login": "carol",
        },
    ]
    return pd.DataFrame(data)


@pytest.fixture
def expert_ids_df() -> pd.DataFrame:
    """Return a small dataframe of expert identifications."""
    data = [
        {
            "observation_id": 101,
            "user_id": 10,
            "identification_id": 1001,
            "created_at": pd.Timestamp("2024-04-01"),
            "taxon_id": 200,
            "name": "Dr. Expert",
            "login": "expert1",
            "expertise": "Plant",
            "est_id": 123,
            "elcode": "ABC123",
        },
        {
            "observation_id": 101,
            "user_id": 11,
            "identification_id": 1002,
            "created_at": pd.Timestamp("2024-04-02"),
            "taxon_id": 200,
            "name": "Prof. Smith",
            "login": "smith",
            "expertise": "Plant",
            "est_id": 123,
            "elcode": "ABC123",
        },
        {
            "observation_id": 102,
            "user_id": 12,
            "identification_id": 1003,
            "created_at": pd.Timestamp("2024-04-04"),
            "taxon_id": None,
            "name": "Dr. Reviewer",
            "login": "reviewer",
            "expertise": "Plant",
            "est_id": 124,
            "elcode": "XYZ456",
        },
    ]
    return pd.DataFrame(data)


@pytest.fixture
def annotations_df() -> pd.DataFrame:
    """Return a simple annotation log."""
    return pd.DataFrame([
        {"observation_id": 101, "annotation_label": "Phenology", "value_label": "Flowering"},
        {"observation_id": 101, "annotation_label": "Sex", "value_label": "Male"},
        {"observation_id": 102, "annotation_label": "Life Stage", "value_label": "Adult"},
    ])


# ---------------------------------------------------------------------------
# run_review
# ---------------------------------------------------------------------------

class TestRunReview:
    def test_run_review_adds_expert_statuses_and_annotation_details(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()

        observations = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)
        mask_101 = observations["observation_id"] == 101
        mask_102 = observations["observation_id"] == 102

        assert (
            observations["expert_verified"].tolist() == ["Yes", "Disagreement", "No"]
        )

        assert observations.loc[mask_101, "identifiedBy"].iat[0] == "Prof. Smith"
        assert observations.loc[mask_101, "dateIdentified"].iat[0].strftime("%Y-%m-%d") == "2024-04-02"
        assert observations.loc[mask_101, "identificationReferences"].iat[0] == "Prof. Smith, Dr. Expert"

        assert observations.loc[mask_102, "identifiedBy"].iat[0] is None
        assert observations.loc[mask_102, "dateIdentified"].iat[0] is pd.NaT
        assert observations.loc[mask_102, "identificationReferences"].iat[0] == "Dr. Reviewer"

        assert observations.loc[mask_101, "annotations"].iat[0] == "Phenology: Flowering; Sex: Male"
        assert observations.loc[mask_102, "annotations"].iat[0] == "Life Stage: Adult"
        assert observations["project_license"].tolist() == [None, "cc-by", None]
        assert observations["permission_to_use"].tolist() == [True, True, True]

    def test_run_review_with_no_experts_or_annotations(self):
        observations_df = pd.DataFrame({
            "observation_id": [101],
            "observer_id": [1],
            "license": ["cc0"],
        })
        expert_ids_df = pd.DataFrame(
            columns=["observation_id", "identifier_name", "created_at", "taxon_id", "name", "login"]
        )
        annotations_df = pd.DataFrame(columns=["observation_id", "annotation_label", "value_label"])

        reviewer = Reviewer()
        observations = reviewer.run_review(observations_df, expert_ids_df, annotations_df, set())

        assert observations["expert_verified"].iat[0] == "No"
        assert observations["annotations"].iat[0] == ""
        assert observations["identificationReferences"].iat[0] == ""
        assert observations["permission_to_use"].iat[0] == True

    def test_format_for_export_uses_private_coordinates_when_available(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()
        observations = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = Reviewer._format_for_export(observations)
        row = export_df.loc[export_df["catalogNumber"] == 103].iloc[0]

        assert row["latitude"] == pytest.approx(44.2335)
        assert row["longitude"] == pytest.approx(-123.4352)

# ---------------------------------------------------------------------------
# _merge_locations
# ---------------------------------------------------------------------------

class TestMergeLocations:
    def test_reveals_private_coordinates_when_obscured(self):
        df = pd.DataFrame({
            "obscured": [True],
            "latitude": [44.0], "longitude": [-123.0],
            "latitude_private": [44.5], "longitude_private": [-123.5],
            "place_guess": ["Public place"], "place_guess_private": ["Private place"],
            "coordinate_precision": [5], "coordinate_precision_public": [50],
        })
        result = Reviewer._merge_locations(df)

        assert result["latitude"].iat[0] == 44.5
        assert result["longitude"].iat[0] == -123.5
        assert result["obscured"].iat[0] == False
        assert result["place_guess"].iat[0] == "Private place"
        assert result["coordinate_precision"].iat[0] == 5

    def test_stays_obscured_when_private_coordinates_missing(self):
        df = pd.DataFrame({
            "obscured": [True],
            "latitude": [44.0], "longitude": [-123.0],
            "latitude_private": [None], "longitude_private": [None],
            "place_guess": ["Public place"], "place_guess_private": [None],
            "coordinate_precision": [None], "coordinate_precision_public": [50],
        })
        result = Reviewer._merge_locations(df)

        assert result["latitude"].iat[0] == 44.0
        assert result["longitude"].iat[0] == -123.0
        assert result["obscured"].iat[0] == True
        assert result["place_guess"].iat[0] == "Public place"
        assert result["coordinate_precision"].iat[0] == 50

    def test_not_obscured_uses_public_fields_and_clears_obscured_flag(self):
        """Even though private data is populated, an observation that was never marked
        obscured in the first place should keep using its public fields."""
        df = pd.DataFrame({
            "obscured": [False],
            "latitude": [44.0], "longitude": [-123.0],
            "latitude_private": [44.5], "longitude_private": [-123.5],
            "place_guess": ["Public place"], "place_guess_private": ["Private place"],
            "coordinate_precision": [None], "coordinate_precision_public": [50],
        })
        result = Reviewer._merge_locations(df)

        assert result["latitude"].iat[0] == 44.0
        assert result["longitude"].iat[0] == -123.0
        assert result["obscured"].iat[0] == False
        assert result["place_guess"].iat[0] == "Public place"
        assert result["coordinate_precision"].iat[0] == 50


# ---------------------------------------------------------------------------
# _add_evidence_type
# ---------------------------------------------------------------------------

class TestAddEvidenceType:
    def test_photo_and_recording(self):
        df = pd.DataFrame({"has_photo": [True], "has_recording": [True]})
        result = Reviewer._add_evidence_type(df)
        assert result["evidence_type"].iat[0] == "Photograph, Audio"

    def test_photo_only(self):
        df = pd.DataFrame({"has_photo": [True], "has_recording": [False]})
        result = Reviewer._add_evidence_type(df)
        assert result["evidence_type"].iat[0] == "Photograph"

    def test_recording_only(self):
        df = pd.DataFrame({"has_photo": [False], "has_recording": [True]})
        result = Reviewer._add_evidence_type(df)
        assert result["evidence_type"].iat[0] == "Audio"

    def test_neither(self):
        df = pd.DataFrame({"has_photo": [False], "has_recording": [False]})
        result = Reviewer._add_evidence_type(df)
        assert result["evidence_type"].iat[0] == ""


# ---------------------------------------------------------------------------
# _add_project_licenses / _evaluate_licenses
# ---------------------------------------------------------------------------

class TestAddProjectLicenses:
    def test_sets_cc_by_for_project_members(self):
        observer_ids = pd.Series([1, 2, 3])
        result = Reviewer._get_project_licenses(observer_ids, {1, 3})
        assert result.tolist() == ["cc-by", None, "cc-by"]

    def test_empty_project_members_sets_none_for_all(self):
        observer_ids = pd.Series([1, 2])
        result = Reviewer._get_project_licenses(observer_ids, set())
        assert result.tolist() == [None, None]


class TestEvaluateLicenses:
    def test_allowed_license_grants_permission(self):
        observations = pd.DataFrame({"observer_id": [1], "license": ["cc0"], "project_licenses": [None]})
        result = Reviewer._evaluate_licenses(observations["license"], observations["project_licenses"])
        assert result[0] == True

    def test_disallowed_license_without_project_membership_denies_permission(self):
        observations = pd.DataFrame({"observer_id": [1], "license": ["all-rights-reserved"], "project_licenses": [None]})
        result = Reviewer._evaluate_licenses(observations["license"], observations["project_licenses"])
        assert result[0] == False

    def test_disallowed_license_but_project_member_grants_permission(self):
        """A project member's observation gets an implicit cc-by project_license even if
        the observation's own license isn't in the allowed list."""
        observations = pd.DataFrame({"observer_id": [1], "license": ["all-rights-reserved"], "project_licenses": ["cc0"]})
        result = Reviewer._evaluate_licenses(observations["license"], observations["project_licenses"])
        assert result[0] == True


# ---------------------------------------------------------------------------
# _rename_columns
# ---------------------------------------------------------------------------

class TestRenameColumns:
    def test_renames_expected_columns(self):
        df = pd.DataFrame({
            "observation_id": [1],
            "uuid": ["u"],
            "observed_on": ["2024-01-01"],
            "observed_on_string": ["Jan 1, 2024"],
            "description": ["desc"],
            "place_guess": ["place"],
            "coordinate_precision": [10],
            "license": ["cc-by"],  # not in the rename map, stays the same
        })
        result = Reviewer._rename_columns(df)
        assert list(result.columns) == [
            "catalogNumber", "UniqueSurveyID", "v_date", "visit_date",
            "v_note", "directions", "DISTANCE", "license",
        ]


# ---------------------------------------------------------------------------
# _construct_annotation_field
# ---------------------------------------------------------------------------

class TestConstructAnnotationField:
    def test_multiple_annotations_joined_with_semicolon(self):
        df = pd.DataFrame([
            {"annotation_label": "Phenology", "value_label": "Flowering"},
            {"annotation_label": "Sex", "value_label": "Male"},
        ])
        assert Reviewer._construct_annotation_field(df) == "Phenology: Flowering; Sex: Male"

    def test_single_annotation(self):
        df = pd.DataFrame([{"annotation_label": "Life Stage", "value_label": "Adult"}])
        assert Reviewer._construct_annotation_field(df) == "Life Stage: Adult"

    def test_no_annotations_returns_empty_string(self):
        df = pd.DataFrame(columns=["annotation_label", "value_label"])
        assert Reviewer._construct_annotation_field(df) == ""


# ---------------------------------------------------------------------------
# _evaluate_expert_agreement
# ---------------------------------------------------------------------------

class TestEvaluateExpertAgreement:
    def test_all_agree_marks_yes(self):
        observation_ids = pd.Series([101])
        expert_ids = pd.DataFrame({"observation_id": [101, 101], "taxon_id": [10, 10]})
        expert_verified = Reviewer._evaluate_expert_agreement(observation_ids, expert_ids)
        assert expert_verified[0] == "Yes"

    def test_any_disagreement_marks_disagreement(self):
        observation_ids = pd.Series([101])
        expert_ids = pd.DataFrame({"observation_id": [101, 101], "taxon_id": [10, None]})
        expert_verified = Reviewer._evaluate_expert_agreement(observation_ids, expert_ids)
        assert expert_verified[0] == "Disagreement"

    def test_no_expert_ids_marks_no(self):
        observation_ids = pd.Series([101, 102])
        expert_ids = pd.DataFrame({"observation_id": [101], "taxon_id": [10]})
        expert_verified = Reviewer._evaluate_expert_agreement(observation_ids, expert_ids)
        assert expert_verified[1] == "No"


# ---------------------------------------------------------------------------
# _add_identified_by
# ---------------------------------------------------------------------------

class TestAddIdentifiedBy:
    def test_picks_most_recent_valid_identification(self):
        obs_raw = pd.DataFrame({"observation_id": [101], "expert_verified": ["Yes"],})
        expert_ids = pd.DataFrame({
            "observation_id": [101, 101],
            "identifier_name": ["Older Expert", "Newer Expert"],
            "created_at": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")],
            "taxon_id": [10, 10],
        })
        identified_by, date_identified = Reviewer._get_identified_by(obs_raw["observation_id"], obs_raw["expert_verified"], expert_ids)
        assert identified_by[0] == "Newer Expert"
        assert date_identified[0] == pd.Timestamp("2024-02-01")

    def test_ignores_identifications_with_null_taxon_id(self):
        observations = pd.DataFrame({
            "observation_id": [101], "expert_verified": ["Yes"],
        })
        expert_ids = pd.DataFrame({
            "observation_id": [101, 101],
            "identifier_name": ["Disagreeing Expert", "Agreeing Expert"],
            "created_at": [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-01-01")],
            "taxon_id": [None, 10],
        })
        identified_by, _ = Reviewer._get_identified_by(observations["observation_id"], observations["expert_verified"], expert_ids)
        assert identified_by[0] == "Agreeing Expert"

    def test_wipes_identified_by_for_unverified_observations(self):
        observations = pd.DataFrame({
            "observation_id": [101, 102], "expert_verified": ["No", "Disagreement"],
        })
        expert_ids = pd.DataFrame({
            "observation_id": [101, 102],
            "identifier_name": ["Some Expert", "Other Expert"],
            "created_at": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
            "taxon_id": [10, 10],
        })
        identified_by, date_identified = Reviewer._get_identified_by(observations["observation_id"], observations["expert_verified"], expert_ids)
        assert identified_by.isna().all()
        assert date_identified.isna().all()


# ---------------------------------------------------------------------------
# _add_identification_references
# ---------------------------------------------------------------------------

class TestAddIdentificationReferences:
    def test_joins_unique_names_most_recent_first(self):
        observations = pd.DataFrame({"observation_id": [101]})
        expert_ids = pd.DataFrame({
            "observation_id": [101, 101],
            "identifier_name": ["Older Expert", "Newer Expert"],
            "created_at": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")],
        })
        references = Reviewer._add_references(observations["observation_id"], expert_ids)
        assert references[0] == "Newer Expert, Older Expert"

    def test_filters_null_identifier_names(self):
        observations = pd.DataFrame({"observation_id": [101]})
        expert_ids = pd.DataFrame({
            "observation_id": [101, 101],
            "identifier_name": [None, "Named Expert"],
            "created_at": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")],
        })
        references = Reviewer._add_references(observations["observation_id"], expert_ids)
        assert references[0] == "Named Expert"

    def test_observation_with_no_experts_gets_empty_string(self):
        observations = pd.DataFrame({"observation_id": [101, 102]})
        expert_ids = pd.DataFrame({
            "observation_id": [101],
            "identifier_name": ["Some Expert"],
            "created_at": [pd.Timestamp("2024-01-01")],
        })
        references = Reviewer._add_references(observations["observation_id"], expert_ids)
        assert references[0] == "Some Expert"
        assert references[1] == ""


# ---------------------------------------------------------------------------
# clean names
# ---------------------------------------------------------------------------

class TestCleanNames:
    def test_clean_names_prefers_public_name_to_login(self):
        df = pd.DataFrame({
            "name": ["Dr. Public Name", "", "   "],
            "login": ["username", "login-2", "login-3"],
        })

        result = Reviewer.pick_name(df["name"], df["login"])

        assert result.tolist() == ["Dr. Public Name", "login-2", "login-3"]


    def test_clean_names_falls_back_to_login_for_nan_name(self):
        df = pd.DataFrame({
            "name": [np.nan, "Real Name"],
            "login": ["fallback-login", "unused-login"],
        })
        result = Reviewer.pick_name(df["name"], df["login"])
        assert result.tolist() == ["fallback-login", "Real Name"]


# ---------------------------------------------------------------------------
# format_for_csv
# ---------------------------------------------------------------------------

class TestFormatForCSV:
    def test_format_for_csv_returns_valid_export_rows(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()
        reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = Reviewer.format_for_csv(reviewed_df)

        assert list(export_df.columns[:10]) == [
            "catalogNumber",
            "UniqueSurveyID",
            "v_date",
            "visit_date",
            "v_by",
            "v_note",
            "directions",
            "latitude",
            "longitude",
            "DISTANCE",
        ]
        assert export_df["catalogNumber"].tolist() == [101, 102, 103]
        assert export_df["expert_verified"].tolist() == ["Yes", "Disagreement", "No"]
        assert export_df["identificationReferences"].tolist() == [
            "Prof. Smith, Dr. Expert",
            "Dr. Reviewer",
            "",
        ]
        assert export_df["annotations"].tolist() == [
            "Phenology: Flowering; Sex: Male",
            "Life Stage: Adult",
            "",
        ]


# ---------------------------------------------------------------------------
# format_for_gdb
# ---------------------------------------------------------------------------

class TestFormatForGdb:
    def test_returns_validated_dataframe(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()
        reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = Reviewer.format_for_gdb(reviewed_df)

        assert len(export_df) == 3
        assert export_df["catalogNumber"].tolist() == [101, 102, 103]

    def test_column_order_matches_reorder_clean_columns(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()
        reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = Reviewer.format_for_gdb(reviewed_df)

        assert list(export_df.columns) == [
            "catalogNumber", "UniqueSurveyID", "v_date", "visit_date", "v_by", "v_note",
            "directions", "latitude", "longitude", "DISTANCE", "sci_name", "search_type",
            "Dataset", "dist_unit", "sf_type", "est_id", "element_type_species", "element_type",
            "scientific_name", "common_name", "element_name", "family", "author", "egt_uid",
            "srank", "track_status", "explorer", "explorer_link", "elcode", "growth_habit",
            "duration", "date_option", "detected_ind", "ownerInstitutionCode", "dateIdentified",
            "identifiedBy", "identificationReferences", "evidence_type", "url", "obscured",
            "license", "project_license", "permission_to_use", "annotations", "expert_verified",
        ]

    def test_static_columns_populated(self, observations_df, expert_ids_df, annotations_df):
        project_members = {2}
        reviewer = Reviewer()
        reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = reviewer.format_for_gdb(reviewed_df)

        assert (export_df["search_type"] == "Element").all()
        assert (export_df["Dataset"] == "iNaturalist").all()
        assert (export_df["dist_unit"] == "Meters").all()
        assert (export_df["sf_type"] == "point").all()
        assert (export_df["date_option"] == "exact").all()
        assert (export_df["detected_ind"] == "Y").all()
        assert (export_df["ownerInstitutionCode"] == "iNaturalist").all()

    def test_date_columns_remain_datetime(self, observations_df, expert_ids_df, annotations_df):
        """Unlike format_for_csv, format_for_gdb doesn't stringify dates - ExportSchema
        expects v_date/dateIdentified as actual datetimes."""
        project_members = {2}
        reviewer = Reviewer()
        reviewed_df = reviewer.run_review(observations_df, expert_ids_df, annotations_df, project_members)

        export_df = reviewer.format_for_gdb(reviewed_df)

        assert pd.api.types.is_datetime64_any_dtype(export_df["v_date"])