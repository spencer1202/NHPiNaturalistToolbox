"""
This module provides the ability to run a full review on the observation data pulled from the 
iNaturalist API by cross-referencing identifications against an experts list, evaluating
licenses, compiling annotations, preparing the data for export, and exporting it to a csv.
"""
# Standard imports
from typing import Optional

# Third-party imports
import pandas as pd
import numpy as np

# Local imports
from inatdatapipeline.schemas.validation import ExportSchema

DATE_FORMAT = "%Y-%m-%d"

class Review:
    """
    Runs a review of the observations. Provides functions for flagging observations identified by 
    experts, adding a column with expert names, adding an annotations column, inserting project 
    licenses, and flagging observations with the needed licenses.
    """
    def __init__(self, observations_df: pd.DataFrame):
        """
        observations_df:
            Dataframe of full observation records
        """
        self.observations = observations_df

    # ---------------------------------------------------------------------------
    # Expert identifications
    # ---------------------------------------------------------------------------
    def _get_last_identification(self, expert_ids: pd.DataFrame) -> Optional[tuple[str, str]]:
        """
        Returns a tuple with the name and date of the last expert identification.

        The expert identifications should be filtered for just one observation.
        """
        if expert_ids is None:
            raise ValueError("Missing argument: expert_ids must not be None")

        if expert_ids.empty:
            return None

        row = expert_ids.loc[
            expert_ids["created_at"].idxmax()
        ]
        return (row["identifier_name"], row["created_at"].strftime("%Y-%m-%d"))


    def add_identified_by(self, expert_ids: pd.DataFrame):
        """
        Add identifiedBy and dateIdentified columns to the observations dataframe.
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
        self.observations = self.observations.merge(
            latest_experts[["observation_id", "identifiedBy", "dateIdentified"]],
            on="observation_id",
            how="left"
        )

        # Wipe out data for rows where expert_verified is False
        unverified_mask = self.observations["expert_verified"].isin(["No", "Disagreement"])
        self.observations.loc[unverified_mask, ["identifiedBy", "dateIdentified"]] = None


    def evaluate_expert_agreement(self, expert_ids: pd.DataFrame):
        """
        Adds an "expert_verified" column that's true if there is at least one expert identification
        and all expert identifications agree with the community taxon.
        """
        disagreements = (
            expert_ids
            .groupby("observation_id")["taxon_id"]
            .apply(lambda x: x.isna().any())
        )
        obs_status = self.observations["observation_id"].map(disagreements)
        print(obs_status.head(20))

        self.observations["expert_verified"] = np.select(
            [
                obs_status.isna(),         # observation not in expert ids
                obs_status == True,  # observation in expert ids, at least 1 id doesn't agree
                obs_status == False  # observation in expert ids and all ids agree
            ],
            ["No", "Disagreement", "Yes"],
            default="No"
        )

    def add_identification_references(self, expert_ids: pd.DataFrame):
        """
        Adds a new string field to observations called "identificationReferences", which is a list 
        of all the experts who left agreeing identifications on the observation (ordered by most 
        recent).
        """
        expert_ids_sorted = expert_ids.sort_values("created_at", ascending=False)
        all_experts_series = (
            expert_ids_sorted.dropna(subset=["identifier_name"])
            .groupby("observation_id")["identifier_name"]
            .apply(lambda names: ", ".join(names.unique()))
        )
        self.observations["identificationReferences"] = (
            self.observations["observation_id"]
            .map(all_experts_series)
            .fillna("")
        )


    # ---------------------------------------------------------------------------
    # Annotations
    # ---------------------------------------------------------------------------
    def compile_annotations(self, annotations):
        """
        Adds a new field to observations called "annotations", which is a ; separated list of
        annotations left on the observation in the form 'category: value'.
        """
        self.observations["annotations"] = self.observations.apply(
            lambda x: self._compile_anotations(
                annotations[annotations["observation_id"] == x["observation_id"]]
            ),
            axis="columns"
        )


    def _compile_anotations(self, annotations_df: pd.DataFrame):
        """
        Construct a string with all of the annotations in the dataframe. 

        The annotations should be filtered for just one observation.
        """
        strings = []
        for annotation in annotations_df.to_dict(orient="records"):
            strings.append(f"{annotation["annotation_label"]}: {annotation["value_label"]}")

        if len(strings) > 0:
            return "; ".join(strings)
        return ""


    # ---------------------------------------------------------------------------
    # License review
    # ---------------------------------------------------------------------------
    def _add_project_licenses(self, project_members: set) -> pd.DataFrame:
        """
        Adds a field to observations called project_license, which is populated with "cc-by" for
        all observations created by users whose ID is in the project members set.
        """
        member_mask = self.observations["observer_id"].isin(project_members)
        self.observations["project_license"] = np.where(
            member_mask,
            "cc-by",
            None
        )
        return self.observations


    def evaluate_licenses(self, project_members: set) -> pd.DataFrame:
        """
        Adds a project license field to mark observations made by project members, then populates
        a "permission_to_use" field with True if the observation has an appropriate license and 
        false otherwise. Mutates and returns self.observations.
        """
        self._add_project_licenses(project_members)
        allowed_licenses = ["cc0", "cc-by", "cc-by-nc"] #TODO add to configuration file
        allowed_mask = (
            self.observations["license"].isin(allowed_licenses)
            | self.observations["project_license"].isin(allowed_licenses)
        )
        self.observations["permission_to_use"] = np.where(
            allowed_mask,
            True,
            False
        )
        return self.observations


    def export(self, file_path: str):
        """
        Put the observations dataframe into export format and export it to a csv at the given 
        file path.
        """
        # TODO split into more specialized functions
        df = self.observations.copy()

        # Convert dates to strings
        for col in df.select_dtypes(include="datetime").columns:
            df[col] = df[col].dt.strftime(DATE_FORMAT)

        # Populate v_by
        df["v_by"] = self.clean_names(df)

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
        df["latitude"] = np.where(
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

        # Fill null string fields with empty string
        for col in df.select_dtypes(include=[str, "object"]).columns:
            df[col] = df[col].fillna("")

        # Populate static columns
        df["search_type"] = "Element"
        df["Dataset"] = "iNaturalist"
        df["dist_unit"] = "Meters"
        df["sf_type"] = "point"
        df["element_type_species"] = df["element_type"]
        df["date_option"] = "exact"
        df["detected_ind"] = "Y"
        df["ownerInstitutionCode"] = "iNaturalist"

        # Populate evidence type
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
        df = df.rename(columns=renames)

        df_clean = ExportSchema.validate(df)

        # Reorder columns
        # pylint: disable=duplicate-code
        df_clean = df_clean[[
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

        df_clean.to_csv(file_path, index=False)
        return df_clean


    @staticmethod
    def clean_names(df: pd.DataFrame):
        """
        Create a series that uses the user's name if present and their 
        their username if not.
        """
        return (
            df["name"]
            .replace(r"^\s*$", np.nan, regex=True)
            .fillna(df["login"])
        )
