import pandas as pd
import pytest

from inatdatapipeline.client import review
from inatdatapipeline.schemas import validation


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
# latest expert selection
# ---------------------------------------------------------------------------
# _get_last_identification is no longer used; the latest-expert selection is now
# handled in _add_identified_by by sorting by created_at and dropping duplicate
# observation ids after filtering out null taxon_id values.
# The behavior is already covered by the run_review assertions below.

# ---------------------------------------------------------------------------
# run_review
# ---------------------------------------------------------------------------

def test_run_review_adds_expert_statuses_and_annotation_details(observations_df, expert_ids_df, annotations_df):
    project_members = {2}
    reviewer = review.Reviewer(observations_df)

    reviewer.run_review(expert_ids_df, annotations_df, project_members)
    mask_101 = reviewer.observations["observation_id"] == 101
    mask_102 = reviewer.observations["observation_id"] == 102

    assert (
        reviewer.observations["expert_verified"].tolist() == ["Yes", "Disagreement", "No"]
    )

    assert reviewer.observations.loc[mask_101, "identifiedBy"].iat[0] == "Prof. Smith"
    assert reviewer.observations.loc[mask_101, "dateIdentified"].iat[0].strftime("%Y-%m-%d") == "2024-04-02"
    assert reviewer.observations.loc[mask_101, "identificationReferences"].iat[0] == "Prof. Smith, Dr. Expert"

    assert reviewer.observations.loc[mask_102, "identifiedBy"].iat[0] is None
    assert reviewer.observations.loc[mask_102, "dateIdentified"].iat[0] is pd.NaT
    assert reviewer.observations.loc[mask_102, "identificationReferences"].iat[0] == "Dr. Reviewer"

    assert reviewer.observations.loc[mask_101, "annotations"].iat[0] == "Phenology: Flowering; Sex: Male"
    assert reviewer.observations.loc[mask_102, "annotations"].iat[0] == "Life Stage: Adult"
    assert reviewer.observations["project_license"].tolist() == [None, "cc-by", None]
    assert reviewer.observations["permission_to_use"].tolist() == [True, True, True]

def test_format_for_export_uses_private_coordinates_when_available(observations_df, expert_ids_df, annotations_df):
    project_members = {2}
    reviewer = review.Reviewer(observations_df)
    reviewer.run_review(expert_ids_df, annotations_df, project_members)

    export_df = reviewer._format_for_export()
    row = export_df.loc[export_df["catalogNumber"] == 103].iloc[0]

    assert row["latitude"] == pytest.approx(44.2335)
    assert row["longitude"] == pytest.approx(-123.4352)

# ---------------------------------------------------------------------------
# clean names
# ---------------------------------------------------------------------------

def test_clean_names_prefers_public_name_to_login():
    df = pd.DataFrame({
        "name": ["Dr. Public Name", "", "   "],
        "login": ["username", "login-2", "login-3"],
    })

    result = review.Reviewer._clean_names(df)

    assert result.tolist() == ["Dr. Public Name", "login-2", "login-3"]


# ---------------------------------------------------------------------------
# format_for_export
# ---------------------------------------------------------------------------

def test_format_for_csv_returns_valid_export_rows(observations_df, expert_ids_df, annotations_df):
    project_members = {2}
    reviewer = review.Reviewer(observations_df)
    reviewer.run_review(expert_ids_df, annotations_df, project_members)

    export_df = reviewer.format_for_csv()

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
