"""
This module contains a dataclass and a helper function for fetching annotation categories and 
values from iNaturalist.

iNaturalist annotations are stored as a pair of IDs representing a category (e.g. Life Stage) and 
a value (e.g. Adult or Juvenile). The labels associated with these IDs are only available 
throught iNaturalist's controlled terms API. This module is responsible for fetching the entire 
list of controlled terms and returning them as categories and values, each with their respective
labels.
"""
import logging
from dataclasses import dataclass, field

import requests

from inatdatapipeline.client.authentication import INaturalistAuth, TIMEOUT

logger = logging.getLogger("pipeline")

@dataclass
class AnnotationOptions:
    """
    This object represents all of the possible annotation options and values available in 
    iNaturalist.
    """
    categories: list[dict] = field(default_factory=list)
    values: list[dict] = field(default_factory=list)


def fetch_annotations(auth: INaturalistAuth) -> AnnotationOptions:
    """
    Fetch all available annotations and annotation values from iNaturalist.
    """
    url = "https://api.inaturalist.org/v2/controlled_terms?fields=all"
    headers = auth.get_auth_headers()

    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as ex:
        raise ValueError("Request to fetch annotation options failed.") from ex

    data = response.json()
    results = data.get("results", [])
    if not results:
        raise ValueError("Annotation API response did not contain results.")

    annotations = AnnotationOptions()
    for result in results:
        annotation_id = result.get("id")
        annotation = {
            "annotation_id": annotation_id,
            "label": result.get("label")
        }
        annotations.categories.append(annotation)

        # Get values for this annotation
        values = result.get("values")
        if not values:
            raise ValueError(
                f"Annotation has no values. (ID={result.get('id')}, label={result.get('label')})"
            )
        for value in values:
            val = {
                "value_id": value.get("id"),
                "annotation_id": annotation_id,
                "label": value.get("label")
            }
            annotations.values.append(val)

    return annotations