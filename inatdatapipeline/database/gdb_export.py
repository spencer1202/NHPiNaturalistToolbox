import os
import arcpy
import numpy as np
import pandas as pd

DTYPE_TO_ARCPY = {
    int: "LONG",
    float: "DOUBLE",
    bool: "SHORT",
    str: "TEXT",
    "datetime64[ns]": "DATE",
}

def write_point_feature_class(
    df: pd.DataFrame,
    out_feature_class: str,
    x_field: str = "longitude",
    y_field: str = "latitude",
    spatial_reference: int = 4326,
    text_length: int = 255,
    overwrite: bool = True,
) -> str:
    """
    Write a dataframe of point records to a feature class.

    Args:
        out_feature_class: Full catalog path to output feature class.
    """
    out_gdb, fc_name = os.path.split(out_feature_class)

    if overwrite and arcpy.Exists(out_feature_class):
        arcpy.management.Delete(out_feature_class)

    sr = arcpy.SpatialReference(spatial_reference)
    arcpy.management.CreateFeatureclass(
        out_gdb, fc_name, geometry_type="POINT", spatial_reference=sr
    )

    attr_fields = [col for col in df.columns if col not in (x_field, y_field)]
    for col in attr_fields:
        arcpy_type = DTYPE_TO_ARCPY.get(str(df[col].dtype), "TEXT")
        arcpy.management.AddField(
            out_feature_class,
            field_name=col,
            field_type=arcpy_type,
            field_length=text_length if arcpy_type == "TEXT" else None,
        )

    records = df.where(pd.notna(df), None)
    cursor_fields = attr_fields + ["SHAPE@XY"]

    with arcpy.da.InsertCursor(out_feature_class, cursor_fields) as cursor:
        for row in records.itertuples(index=False):
            values = [getattr(row, col) for col in attr_fields]
            cursor.insertRow(values + [(getattr(row, x_field), getattr(row, y_field))])

    return out_feature_class