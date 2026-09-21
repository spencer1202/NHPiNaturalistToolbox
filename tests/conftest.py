from unittest.mock import MagicMock, patch
import pytest
import logging
import pandas as pd

from inatdatapipeline.client import (
    observations,
    annotations
)
from inatdatapipeline.client.observations import ObservationResults
from inatdatapipeline.schemas import config
from inatdatapipeline.schemas.validation import (
    ObservationSchema,
    IdentificationsSchema,
    ExpertsSchema
)
from inatdatapipeline.database.db import DBManager
from inatdatapipeline.client.authentication import INaturalistAuth
from inatdatapipeline.client import review

data_file = "tests/data.pkl"

# ---------------------------------------------------------------------------
# Class object fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def auth():
    mock = MagicMock()
    mock.get_auth_headers.return_value = {"Authorization": "Bearer test_token"}
    return mock
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def expert_ids():
    return pd.DataFrame({
        "identification_id" : [1, 2, 3, 4],
        "observation_id"    : [1, 1, 2, 2],
        "user_id"           : [1, 2, 1, 3],
        "login"             : ["user1", "user2", "user1", "user3"],
        "name"              : ["User One", "User Two", "User One", None],
        "taxon_id"          : [1, 1, 9, 2],
        "created_at"        : ["2024-04-15 12:00:00", "2024-04-16 16:30:00", "2024-04-15 18:00:00", "2024-04-15 10:00:00"],
        "est_id"            : [1, 1, 2, 2],
        "elcode"            : ["AA", "AB", "AC", "BD"],
        "expertise"         : ["A%", "AB%", "A%", "B%"]
    })

@pytest.fixture
def experts_raw():
    return pd.DataFrame({
        "iNaturalist_id"                    : [1, 2, 3],
        "Expertise LU"                      : ["A%", "AB%", "B%"],
        "Name"                              : ["User 1", "User 2", "User 3"],
        "NatureServe Network Staff Status"  : ["Current", "Former", "No"]
    })

@pytest.fixture
def experts_clean(experts_raw):
    return ExpertsSchema.from_raw(experts_raw)

@pytest.fixture
def full_observation_from_sqlite_df():
    return pd.DataFrame({
        "observation_id":               [1, 2],
        "uuid":                         ["j483js81", "hjfs923j589"],
        "observer_id":                  [10, 11],
        "name":                         ["Brad", "Jess"],
        "login":                        ["Brad1234", "animallover99"],
        "taxon_id":                     [1, 2],
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
        "captive_cultivated":           [0, 1],
        "place_guess":                  ["Near creek", "In forest"],
        "place_guess_private":          [None, "123 Private St"],
        "obscured":                     [0, 1],
        "has_photo":                    [1, 0],
        "has_recording":                [0, 1],
        "observed_on":                  ["2024-03-15", "2024-03-16"],
        "created_at":                   ["2024-03-16", "2024-03-17"],
        "updated_at":                   ["2024-03-17", "2024-03-18"],
        "est_id":                       [1, 2],
        "sci_name":                     ["Aster alpinus var. vierhapperi", "Carex stipata"],
        "element_type":                 ["Plant", "Plant"],
        "scientific_name":              ["<i>Aster alpinus var. vierhapperi</i>", "<i>Carex stipata</i>"],
        "common_name":                  ["Alpine Aster", "Tussock Sedge"],
        "element_name":                 ["1", "2"],
        "family":                       ["Asteraceae", "Cyperaceae"],
        "author":                       ["L.", "Aiton"],
        "egt_uid":                      ["uid1", "uid2"],
        "srank":                        ["S1", "S2"],
        "track_status":                 ["Track", "Track"],
        "explorer":                     ["url1", "url2"],
        "explorer_link":                ["link1", "link2"],
        "elcode":                       ["code1", "code2"],
        "growth_habit":                 ["Forb", "Graminoid"],
        "duration":                     ["Perennial", "Perennial"]
    })
# ---------------------------------------------------------------------------
