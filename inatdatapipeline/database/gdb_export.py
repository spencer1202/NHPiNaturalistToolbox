import os
import arcpy
import numpy as np
import pandas as pd
import pandera as pa
import typing
from inatdatapipeline.schemas import validation
import logging

logger = logging.getLogger("pipeline")

DTYPE_TO_ARCPY = {
    int: "LONG",
    float: "DOUBLE",
    bool: "SHORT",
    str: "TEXT",
    np.datetime64: "DATE",
    pa.DateTime: "DATE"
}

def build_field_schema(
    model: type[pa.DataFrameModel],
    default_text_length: int = 255,
    text_length_overrides: dict[str, int] | None = None,
) -> list[list[str, str, str, int | None]]:
    """
    Derive an arcpy field schema (name, type, alias, length) from a pandera DataFrameModel's
    annotations, preserving declaration order.
    """
    overrides = text_length_overrides or {}
    fields = []
    for name, annotation in model.__annotations__.items():
        (py_type,) = typing.get_args(annotation) or (str,)
        arcpy_type = DTYPE_TO_ARCPY.get(py_type, "TEXT")
        length = overrides.get(name, default_text_length) if arcpy_type == "TEXT" else None
        new_field = [
            name,
            arcpy_type,
            name,
            length
        ]
        fields.append(new_field)
    return fields


def write_point_feature_class(
    df: pd.DataFrame,
    out_feature_class: str,
    x_field: str = "longitude",
    y_field: str = "latitude",
    spatial_reference: int = 4326,
    overwrite: bool = True,
) -> str:
    """
    Write a dataframe of point records to a feature class. 

    Args:
        out_feature_class: Full catalog path to output feature class.
    """
    out_gdb, fc_name = os.path.split(out_feature_class)
    text_length_overrides = {
        "annotations": 1000,
        "identificationReferences": 500,
        "v_note": 5000,
        "explorer_link": 500
    }

    if overwrite and arcpy.Exists(out_feature_class):
        arcpy.management.Delete(out_feature_class)

    logger.debug("Creating feature class...")
    sr = arcpy.SpatialReference(spatial_reference)
    arcpy.management.CreateFeatureclass(
        out_gdb, fc_name, geometry_type="POINT", spatial_reference=sr
    )

    logger.debug("Adding fields...")
    field_schema = build_field_schema(
        validation.ExportSchema, text_length_overrides=text_length_overrides
    )
    arcpy.management.AddFields(out_feature_class, field_schema)

    field_names = [name for name, _, _, _ in field_schema]
    records = df.astype(object).where(pd.notna(df), None)
    cursor_fields = field_names + ["SHAPE@XY"]

    logger.debug("Inserting rows into feature class...")
    with arcpy.da.InsertCursor(out_feature_class, cursor_fields) as cursor:
        count = 0
        total = len(records)
        for row in records.itertuples(index=False):
            count = count + 1
            if count % 500 == 0:
                logger.debug("[Inserting row %i/%i]", count, total)
            values = [getattr(row, c) for c in field_names]
            cursor.insertRow(values + [(getattr(row, x_field), getattr(row, y_field))])

    return out_feature_class