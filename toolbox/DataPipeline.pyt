# -*- coding: utf-8 -*-
###########################################################################
##### Imports #####
import os
import sys
import logging
import importlib
from pathlib import Path
from typing import (
    Optional,
    Any
)
import sqlite3
from requests import HTTPError
import arcpy
import traceback

from inatdatapipeline.database import db

# Add current directory to system path
toolbox_dir = Path(__file__).resolve().parent
if str(toolbox_dir) not in sys.path:
    sys.path.append(str(toolbox_dir))

top_level_dir = toolbox_dir.parent
if str(top_level_dir) not in sys.path:
    sys.path.append(str(top_level_dir))

print(sys.path)

# Import local package
import inatdatapipeline as inat
from inatdatapipeline import (
    pipeline,
)
from inatdatapipeline.client import (
    authentication,
    observations,
    taxa,
    review
)
from inatdatapipeline.schemas import config

importlib.reload(inat)
importlib.reload(authentication)
importlib.reload(observations)
importlib.reload(db)
importlib.reload(pipeline)
importlib.reload(config)
importlib.reload(taxa)
importlib.reload(review)



import inatdatapipeline

##### Global variables #####
user_agent = "iNat_ORBIC_DataPipeline/1.0"
# .sql file with database schema
sql_file_path = top_level_dir.joinpath("inatdatapipeline", "schema.sql")
log_file = "pipeline.log"
log_file_path = top_level_dir.joinpath("logs", log_file)


##### Set up logging #####
class ArcGisHandler(logging.Handler):
    def emit(self, record):
        arcpy.AddMessage(self.format(record))

logger = logging.getLogger("pipeline")
logger.setLevel(logging.DEBUG)

if logger.hasHandlers():
    logger.handlers.clear()

arcgis_handler = ArcGisHandler()
arcgis_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
arcgis_handler.setLevel(logging.INFO)
logger.addHandler(arcgis_handler)

file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M")
)
logger.addHandler(file_handler)


###########################################################################
##### Helper functions #####
def get_auth(
        user_agent: str,
        username: str
) -> tuple[Optional[db.DBManager], Optional[authentication.INaturalistAuth]]:
    """
    Set up iNaturalist authentication using provided user agent and username. Catches exceptions 
    and exits with error message if one occurs.
    """
    try:
        auth: authentication.INaturalistAuth = authentication.INaturalistAuth(user_agent)
        success = auth.generate_access_token(username)
    # Invalid credentials
    except HTTPError as ex:
        raise ValueError("Authentication failed: Invalid credentials.") from ex

    if not success:
        raise ValueError("Could not obtain OAuth2 access token.")

    return auth


def db_setup(db_manager: db.DBManager):
    """
    Helper function that sets up database tables, catches exceptions and exits with an error 
    message if one occurs.
    """
    try:
        with db_manager as conn:
            conn.setup_db(sql_file_path)
    except sqlite3.Error as ex:
        raise ValueError("Error while setting up database.") from ex


def _exit_failure(err: Any = None):
    """
    Optionally log an error message, then exit the program with an error code.
    """
    if err:
        msg_err = traceback.format_exception(None, value=err, tb=None, chain=True)
        msg_debug = traceback.format_exception(err)
        logger.error(str(msg_err))
        logger.debug(msg_debug)

    logger.info("")
    logger.info("Exiting.")
    logger.info("---------------------------------------\n")
    exit(1)


###########################################################################
##### Toolbox class #####
class Toolbox:
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "iNatDataProcessingToolbox"
        self.alias = "toolbox"

        # List of tool classes associated with this toolbox
        self.tools = [
            TaxonMapping,
            DownloadObservations,
            RunReview
        ]

##### Tool base class #####
class Tool:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Tool"
        self.description = ""
        self.db_manager: db.DBManager = None
        self.auth: authentication.INaturalistAuth = None
        

    def getParameterInfo(self):
        """Define the tool parameters."""
        db_file = arcpy.Parameter(
            displayName="Geopackage Database File",
            name="db_file",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        db_file.filter.list = ["gpkg"]

        inat_username = arcpy.Parameter(
            displayName="iNaturalist username",
            name="inat_user",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )

        return [db_file, inat_username]

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        db_param = parameters[0]
        if db_param.valueAsText and db_param.hasError():
            if not os.path.exists(db_param.valueAsText):
                db_param.clearMessage()

    def execute(self, parameters, messages):
        """Behavior common to all tools in the toolbox"""
        db_file = parameters[0].valueAsText
        inat_user = parameters[1].valueAsText

        logger.info("---------------------------------------")
        logger.info("*** iNaturalist Data Pipeline Tool  ***")
        logger.info("---------------------------------------")
        logger.info("File database: %s", db_file)
        logger.info("iNaturalist username: %s", inat_user)
        logger.info("")

        self.db_manager = db.DBManager(db_file)
        self.auth = get_auth(user_agent, inat_user)

        db_setup(self.db_manager)

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return

###########################################################################
##### Taxon mapping tool #####
class TaxonMapping(Tool):
    def __init__(self):
        """TODO description of taxon mapping tool"""
        self.label = "Build Taxon Mapping"
        self.description = "" # TODO insert description

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = super().getParameterInfo()
    
        tracking_list = arcpy.Parameter(
            displayName="Tracking List File",
            name="tracking_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        tracking_list.filter.list = ["csv"]

        name_overrides = arcpy.Parameter(
            displayName="Name Overrides File",
            name="overrides_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        name_overrides.filter.list = ["csv"]

        return params + [tracking_list, name_overrides]

    def execute(self, parameters, messages):
        """Tool source code"""
        super().execute(parameters, messages)

        tracking_csv = parameters[2].valueAsText
        overrides_csv = parameters[3].valueAsText

        try:
            pipeline.build_taxon_mapping(
                tracking_csv,
                overrides_csv,
                self.db_manager,
                self.auth
            )
        except ValueError as ex:
            _exit_failure(ex)


###########################################################################
##### Download observations tool #####
class DownloadObservations(Tool):
    # Request parameters
    PER_PAGE = 200
    BATCH_SIZE = 50

    def __init__(self):
        """TODO description of tool"""
        self.label = "Download iNat Observations"
        self.description = "" # TODO insert description
    
    def getParameterInfo(self):
        """Define the tool parameters"""
        params = super().getParameterInfo()

        place_id = arcpy.Parameter(
            displayName="Place ID",
            name="place_id",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        place_id.value = 10

        quality_grade = arcpy.Parameter(
            displayName="Quality Grade",
            name="quality_grade",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        quality_grade.filter.type = "ValueList"
        quality_grade.filter.list = ["research", "needs_id", "casual"]
        quality_grade.value = "research"

        update_after_days = arcpy.Parameter(
            displayName="Update After Days",
            name="update_after_days",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        update_after_days.value = 30

        project_id = arcpy.Parameter(
            displayName="iNaturalist Project ID",
            name="project_id",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        project_id.value = 247148

        max_observations = arcpy.Parameter(
            displayName="Maximum Observations to Download",
            name="max_observations",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        max_observations.filter.type = "Range"
        max_observations.filter.list = [0, 1000000]
        max_observations.value = 1000

        return params + [place_id, quality_grade, update_after_days, project_id, max_observations]


    def execute(self, parameters, messages):
        """Tool source code"""
        super().execute(parameters, messages)

        place_id = int(parameters[2].value)
        quality_grade = parameters[3].valueAsText.replace(";", ",")
        update_after_days = int(parameters[4].value)
        project_id = int(parameters[5].value)
        max_observations = int(parameters[6].value)

        cfg_obs = config.ObservationsConfig(
            place_id=place_id,
            quality_grade=quality_grade,
            per_page=DownloadObservations.PER_PAGE,
            batch_size=DownloadObservations.BATCH_SIZE,
            update_after_days=update_after_days,
            project_id=project_id,
            max_observations=max_observations
        )
        try:
            pipeline.get_observations(cfg_obs, self.db_manager, self.auth)
        except ValueError as ex:
            _exit_failure(ex)


class RunReview(Tool):
    PER_PAGE = 200

    def __init__(self):
        self.label = "Perform Review of Observations"
        self.description = "" # TODO insert description
    
    def getParameterInfo(self):
        """Define the tool parameters"""
        params = super().getParameterInfo()

        project_id = arcpy.Parameter(
            displayName="iNaturalist Project ID",
            name="project_id",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        project_id.value = 247148

        experts_file = arcpy.Parameter(
            displayName="Experts File",
            name="experts_file",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        experts_file.filter.list = ["csv"]

        experts_id_field = arcpy.Parameter(
            displayName="Experts file iNaturalist ID field",
            name="id_field",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        experts_id_field.parameterDependencies = [experts_file.name]
        experts_id_field.value = "iNaturalist_id"

        experts_expertise_field = arcpy.Parameter(
            displayName="Experts file expertise field",
            name="expertise_field",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        experts_expertise_field.parameterDependencies = [experts_file.name]
        experts_expertise_field.value = "Expertise LU"

        export_csv = arcpy.Parameter(
            displayName="Export CSV",
            name="export_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Output"
        )

        new_fields = [
            project_id, 
            experts_file, 
            experts_id_field,
            experts_expertise_field,
            export_csv
        ]

        return params + new_fields

    def execute(self, parameters, messages):
        super().execute(parameters, messages)

        project_id = int(parameters[2].value)
        cfg_rev = config.ReviewConfig(
            experts_file=parameters[3].valueAsText,
            experts_id_field=parameters[4].valueAsText,
            experts_expertise_field=parameters[5].valueAsText,
            export_csv=parameters[6].valueAsText,

        )
        
        try:
            pipeline.update_project_members(project_id, self.db_manager, self.auth)
            pipeline.update_annotations(self.db_manager, self.auth)
            pipeline.run_review(cfg_rev, self.db_manager)
        except ValueError as ex:
            _exit_failure(ex)
