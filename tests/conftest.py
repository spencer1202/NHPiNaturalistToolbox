import pytest
import logging
import pickle as pkl
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
from inatdatapipeline.db import DBManager
from inatdatapipeline.client.authentication import INaturalistAuth
from inatdatapipeline import __main__
from inatdatapipeline.client import review

data_file = "tests/data.pkl"

# ---------------------------------------------------------------------------
# Fixtures
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
        "taxon_id":          [None, None, None],
        "inat_name":         [None, None, None],
    })

@pytest.fixture
def tracking_df_preprocessed(tracking_df):
    df = tracking_df.copy()
    df["search_name"] = ["Aster alpinus vierhapperi", "Carex stipata", "Salix"]


@pytest.fixture
def overrides_df():
    return pd.DataFrame({
        "est_id":    [1],
        "inat_name": ["Aster alpinus"],
        "taxon_id":  [None]
    })


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
    return ObservationSchema.from_raw(raw_observation_df)


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
    return IdentificationsSchema.from_raw(raw_identifications_df)

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



@pytest.fixture(scope="session", autouse=True)
def logger():
    logger = logging.getLogger('pipeline')
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(console_handler)


@pytest.fixture(scope="session")
def core_cfg():
    return config.CoreConfig(
        db_file     = "data/test_small.db",
        user_agent  = "iNat_ORBIC_DataPipeline/1.0",
        username    = "hspencer1202"
    )






@pytest.fixture(scope="session")
def insert_annotations(db, auth):
    observations.load_annotations(db, auth)


@pytest.fixture(scope="session")
def insert_observations(observation_results, insert_annotations):
    db_manager: DBManager = observation_results["db"]
    results: observations.ObservationResults = observation_results["results"]

    observations.insert_observation_results(results, db_manager)

    return observation_results


@pytest.fixture(scope="session")
def load_annotations(auth):
    return annotations.fetch_annotations(auth)


@pytest.fixture(scope="function")
def all_observations(db) -> pd.DataFrame:
    with db as conn:
        return conn.get_full_observations()


@pytest.fixture(scope="session")
def db(core_cfg):
    return DBManager(core_cfg.db_file)


@pytest.fixture(scope="function")
def annotations_with_labels(db, load_annotations) -> pd.DataFrame:
    with db as conn:
        return conn.select("annotations_with_labels")
