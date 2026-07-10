import pytest
import pandas as pd
import sqlite3

from inatdatapipeline.db import DBManager
from inatdatapipeline.schemas import validation


# Test invalid database file location
def test_invalid_db(core_cfg):
    db_manager = DBManager("not_a_directory/invalid_database.db")
    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        db_manager.connect()


def test_setup_db(core_cfg):
    manager = DBManager(core_cfg.db_file)
    manager.connect()
    manager.setup_db()


def test_get_mappings(core_cfg):
    manager = DBManager(core_cfg.db_file)
    with manager as db:
        db.setup_db()
        df = db.select("mappings")
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Mappings: \n\n{df}")
    print("-------------------------------------------")


def test_get_inat_taxa(core_cfg):
    manager = DBManager(core_cfg.db_file)
    with manager as db:
        df = db.select("inat_taxa")
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"iNat Taxa: \n\n{df}\n")
    df.info()
    print("-------------------------------------------")


def test_expert_identifications(core_cfg):
    manager = DBManager(core_cfg.db_file)
    with manager as db:
        expert_ids_df = db.get_expert_identifications()

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Expert Identifications: \n\n{expert_ids_df.head(10)}\n")
    expert_ids_df.info()
    print("-------------------------------------------")


def test_update_experts(db, experts_clean):
    experts_df = validation.ExpertsSchema.from_raw(experts_clean)   
    
    with db as conn:
        count = conn.update_experts(experts_df)
    
    assert len(experts_df) == count


def test_get_full_observations(db):
    with db as conn:
        df = conn.select("full_observations")
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Full Observations: \n\n{df.head(10)}")
    print("-------------------------------------------")

    df.to_csv("data/output/full_observations.csv", index=False)