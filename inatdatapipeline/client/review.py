"""
This module is responsible for reviewing downloaded observations for expert identification, usage
permissions, and obscured locations. The Reviewer class combines observations with associated 
information from the experts, identifications, annotations, and project members tables.

This module also contains functions that format the reviewed observations for export.

Unlike the taxa and observation modules, transformation functions are contained within the Review
class instead of in the schemas module.
"""
# TODO: refactor export transformation functions out of review module
# Standard imports
from typing import Optional
from dataclasses import dataclass

# Third-party imports
import pandas as pd
import numpy as np
from pandera.typing import DataFrame

# Local imports
from inatdatapipeline import schemas
from inatdatapipeline.config import ReviewConfig

DATE_FORMAT = "%Y-%m-%d"

class Reviewer:
    """
    Runs a review of the observations. Provides functions for flagging observations identified by 
    experts, adding a column with expert names, adding an annotations column, inserting project 
    licenses, and flagging observations with the needed licenses.
    """
    def __init__(self, cfg_review: ReviewConfig = None):
        self.config = cfg_review if cfg_review else ReviewConfig()
        self.reviewed_df: pd.DataFrame = None

    @staticmethod
    def _get_identified_by(observation_ids: pd.Series, expert_verified: pd.Series, expert_ids: pd.DataFrame):
        """
        Returns two new columns, one with the names of the experts who identified observations and
        one with the date the identification was made. Series arguments must share the same index.
        """
        expert_ids_sorted = expert_ids.sort_values("created_at", ascending=False)
        expert_ids_sorted = expert_ids_sorted[expert_ids_sorted["taxon_id"].notna()]
        latest_experts = expert_ids_sorted.drop_duplicates(subset=["observation_id"], keep="first")
        latest_experts = latest_experts.rename(
            columns={
                "identifier_name": "identifiedBy",
                "created_at": "dateIdentified"
            }
        )
        merged_df = pd.merge(
            observation_ids,
            latest_experts[["observation_id", "identifiedBy", "dateIdentified"]],
            on="observation_id",
            how="left"
        )

        # Wipe out data for rows where expert_verified is False
        unverified_mask = expert_verified.isin(["No", "Disagreement"])
        merged_df.loc[unverified_mask, ["identifiedBy", "dateIdentified"]] = None

        return merged_df["identifiedBy"], merged_df["dateIdentified"]

    @staticmethod
    def _evaluate_expert_agreement(observation_ids: pd.Series, expert_ids: pd.DataFrame):
        """        
        Returns an "expert_verified" column that's true if there is at least one expert identification
        and all expert identifications agree with the community taxon.
        """
        disagreements = (
            expert_ids
            .groupby("observation_id")["taxon_id"]
            .apply(lambda x: x.isna().any())
        )
        obs_status = observation_ids.map(disagreements)

        return np.select(
            [
                obs_status.isna(),         # observation not in expert ids
                obs_status == True,  # observation in expert ids, at least 1 id doesn't agree
                obs_status == False   # observation in expert ids and all ids agree
                #ik this is ugly but it's the only method that works for this ¯\_(ツ)_/¯
            ],
            ["No", "Disagreement", "Yes"],
            default="No"
        )

    @staticmethod
    def _add_references(
        observation_ids: pd.Series,
        expert_ids: pd.DataFrame
    ) -> pd.Series:
        """
        Returns a new string field for observations: a list of all the experts who left agreeing 
        identifications on the observation (ordered by most recent).
        """
        expert_ids_sorted = expert_ids.sort_values("created_at", ascending=False)
        all_experts_series = (
            expert_ids_sorted.dropna(subset=["identifier_name"])
            .groupby("observation_id")["identifier_name"]
            .apply(lambda names: ", ".join(names.unique()))
        )
        return (
            observation_ids
            .map(all_experts_series)
            .fillna("")
        )


    # ---------------------------------------------------------------------------
    # Annotations
    # ---------------------------------------------------------------------------
    @staticmethod
    def _compile_annotations(observation_ids: pd.Series, annotations: pd.DataFrame) -> pd.Series:
        """
        Returns a new column for observations which is a ; separated list of all the annotations
        left on the observation in the form 'category: value'.
        """
        return observation_ids.apply(
            lambda x: Reviewer._construct_annotation_field(
                annotations[annotations["observation_id"] == x]
            )
        )

    @staticmethod
    def _construct_annotation_field(annotations_df: pd.DataFrame):
        """
        Construct a string with all of the annotations in the dataframe. 

        The annotations should be filtered for just one observation.
        """
        strings = []
        for annotation in annotations_df.to_dict(orient="records"):
            strings.append("%s: %s" % (annotation["annotation_label"], annotation["value_label"]))

        if len(strings) > 0:
            return "; ".join(strings)
        return ""


    # ---------------------------------------------------------------------------
    # License review
    # ---------------------------------------------------------------------------
    @staticmethod
    def _get_project_licenses(observer_ids: pd.Series, project_members: set) -> pd.DataFrame:
        """
        Returns a series populated with "cc-by" for all observations created by users whose ID is 
        in the project members set.
        """
        member_mask = observer_ids.isin(project_members)
        return np.where(
            member_mask,
            "cc-by",
            None
        )

    @staticmethod
    def _evaluate_licenses(licenses, project_licenses) -> pd.Series:
        """
        Returns a field with True if the observation has an appropriate license and 
        false otherwise. First two arguments must be series with the same index.
        """
        allowed_licenses = ["cc0", "cc-by", "cc-by-nc"] #TODO add to parameters
        allowed_mask = (
            licenses.isin(allowed_licenses)
            | project_licenses.isin(allowed_licenses)
        )
        return np.where(
            allowed_mask,
            True,
            False
        )

    def run_review(
            self,
            observations_df: pd.DataFrame,
            expert_ids_df: pd.DataFrame, 
            annotations_df: pd.DataFrame, 
            project_members: set
    ) -> pd.DataFrame:
        """
        Reviews expert agreement, adds identified_by and identification_references columns, 
        compiles observation annotations, and evaluates observation licenses. Returns a reviewed
        observations dataframe.
        """
        expert_ids_copy = expert_ids_df.copy()
        expert_ids_copy["identifier_name"] = Reviewer.pick_name(
            expert_ids_copy["name"],
            expert_ids_copy["login"]
        )

        reviewed_df = observations_df.copy()
        observation_ids = reviewed_df["observation_id"]

        reviewed_df["expert_verified"] = Reviewer._evaluate_expert_agreement(
            observation_ids,
            expert_ids_copy
        )
        reviewed_df["identifiedBy"], reviewed_df["dateIdentified"] = (
            Reviewer._get_identified_by(observation_ids, reviewed_df["expert_verified"], expert_ids_copy)
        )
        reviewed_df["identificationReferences"] = Reviewer._add_references(observation_ids, expert_ids_copy)
        reviewed_df["annotations"] = Reviewer._compile_annotations(observation_ids, annotations_df)
        reviewed_df["project_license"] = Reviewer._get_project_licenses(reviewed_df["observer_id"], project_members)
        reviewed_df["permission_to_use"] = Reviewer._evaluate_licenses(
            reviewed_df["license"],
            reviewed_df["project_license"]
        )

        self.reviewed_df = reviewed_df
        return self.reviewed_df

    @staticmethod
    def _merge_locations(df) -> pd.DataFrame:
        """
        Merges the public/private location fields (latitude/longiture, precision, place guess) 
        where obscured coordinates are revealed. Location fields are replaced where their private
        counterparts are populated. Rows are recategorized as obscured if they were previously
        marked as obscured AND the private coordinates are not populated.
        
        Returns the modified dataframe (dataframe is modified in-place to conserve space).
        """
        # Merge location fields where obscured coordinates are revealed
        priv_coords_populated_mask = (
            df["obscured"]
            & df["latitude_private"].notna()
            & df["longitude_private"].notna()
        )
        priv_place_populated_mask = (
            df["obscured"]
            & df["place_guess_private"].notna()
        )
        priv_precision_populated_mask = (
            df["obscured"]
            & df["coordinate_precision"].notna()
        )
        not_obscured_mask = (
            ~df["obscured"]
        )

        df["latitude"] = np.where(
            priv_coords_populated_mask,
            df["latitude_private"],
            df["latitude"]
        )
        df["longitude"] = np.where(
            priv_coords_populated_mask,
            df["longitude_private"],
            df["longitude"]
        )
        df["obscured"] = np.where(
            priv_coords_populated_mask | not_obscured_mask,
            False,
            True
        )

        df["place_guess"] = np.where(
            priv_place_populated_mask,
            df["place_guess_private"],
            df["place_guess"]
        )
        df["coordinate_precision"] = np.where(
            priv_precision_populated_mask,
            df["coordinate_precision"],
            df["coordinate_precision_public"]
        )

        return df

    @staticmethod
    def _add_static_columns(df) -> pd.DataFrame:
        """
        Adds any required columns where all values are the same.

        Returns the modified dataframe (dataframe is modified in-place to conserve space).
        """
        df["search_type"] = "Element"
        df["Dataset"] = "iNaturalist"
        df["dist_unit"] = "Meters"
        df["sf_type"] = "point"
        df["element_type_species"] = df["element_type"]
        df["date_option"] = "exact"
        df["detected_ind"] = "Y"
        df["ownerInstitutionCode"] = "iNaturalist"

        return df

    @staticmethod
    def _add_evidence_type(df) -> pd.DataFrame:
        """
        Creates a new "evidence_type" field based on whether each observation had a photo, a
        recording, or both.

        Returns the modified dataframe (dataframe is modified in-place to conserve space).
        """
        photo_mask = df["has_photo"]
        recording_mask = df["has_recording"]
        df["evidence_type"] = np.select(
            [
                photo_mask & recording_mask,
                photo_mask,
                recording_mask
            ],
            [
                "Photograph, Audio",
                "Photograph",
                "Audio"
            ],
            default=""
        )
        return df

    @staticmethod
    def _rename_columns(df) -> pd.DataFrame:
        """
        Renames columns to fit the export format.

        Returns the modified dataframe.
        """
        # Rename columns
        renames = {
            "observation_id"        : "catalogNumber",
            "uuid"                  : "UniqueSurveyID",
            "observed_on"           : "v_date",
            "observed_on_string"    : "visit_date",
            "description"           : "v_note",
            "place_guess"           : "directions",
            "coordinate_precision"  : "DISTANCE"
            # keep license and project_license the same
        }
        return df.rename(columns=renames)


    @staticmethod
    def format_for_gdb(observations: pd.DataFrame):
        df = Reviewer._format_for_export(observations)
        df = schemas.ExportSchema.validate(df)
        df = Reviewer._reorder_clean_columns(df)

        return df

    @staticmethod
    def format_for_csv(observations: pd.DataFrame):
        df = Reviewer._format_for_export(observations)
        
        # Convert dates to strings
        for col in df.select_dtypes(include="datetime").columns:
            df[col] = df[col].dt.strftime(DATE_FORMAT)

        df = Reviewer._reorder_clean_columns(df)

        return df

    @staticmethod
    def _format_for_export(observations: pd.DataFrame):
        """
        Puts the observations dataframe into export format and returns it.
        """
        df = observations.copy()

        df["element_name"] = df["est_id"].astype(str)   # add element name column

        df["explorer_link"] = (
            df["explorer"]
            .apply(lambda x: f"<a href=\"{x}\">View in Explorer</a>")
        )
        df["scientific_name"] = (
            df["sci_name"]
            .apply(lambda x: f"<i>{x}</i>")
        )
        df["v_by"] = Reviewer.pick_name(df["name"], df["login"])
        df = Reviewer._merge_locations(df)

        # Fill null string fields with empty string
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].fillna("")

        df = Reviewer._add_static_columns(df)
        df = Reviewer._add_evidence_type(df)
        df = Reviewer._rename_columns(df)

        return df
    
    @staticmethod
    def _reorder_clean_columns(
        df: DataFrame[schemas.ExportSchema]
    ) -> DataFrame[schemas.ExportSchema]:
        """
        Returns the dataframe with columns in a nicer order.
        """
        # pylint: disable=duplicate-code
        return df[[
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
            "sci_name",
            "search_type",
            "Dataset",
            "dist_unit",
            "sf_type",
            "est_id",
            "element_type_species",
            "element_type",
            "scientific_name",
            "common_name",
            "element_name",
            "family",
            "author",
            "egt_uid",
            "srank",
            "track_status",
            "explorer",
            "explorer_link",
            "elcode",
            "growth_habit",
            "duration",
            "date_option",
            "detected_ind",
            "ownerInstitutionCode",
            "dateIdentified",
            "identifiedBy",
            "identificationReferences",
            "evidence_type",
            "url",
            "obscured",
            "license",
            "project_license",
            "permission_to_use",
            "annotations",
            "expert_verified"
        ]]

    @staticmethod
    def pick_name(names: pd.Series, logins: pd.Series) -> pd.Series:
        """
        Create a series that uses the user's name if present and their their username if not.
        Arguments must be series that share an index.
        """
        return (
            names
            .replace(r"^\s*$", np.nan, regex=True)
            .fillna(logins)
        )

    def validate_experts(self, experts_df: pd.DataFrame) -> pd.DataFrame:
        return schemas.ExpertsSchema.from_raw(
            experts_df,
            self.config.experts_id_field,
            self.config.experts_expertise_field
        )
