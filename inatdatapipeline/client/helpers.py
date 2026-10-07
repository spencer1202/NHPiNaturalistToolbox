"""
This module contains a function for fetching annotation options, a function for fetching project
members, and some miscellaneous helper functions.
"""
import time
import logging
import requests

import pandera.pandas as pa

from inatdatapipeline.client.authentication import INaturalistAuth, TIMEOUT

logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def report_schema_error(ex: pa.errors.SchemaError):
    logger.error("Schema name: %s", ex.schema.name)
    logger.error("Failed check: %s", ex.check)
    logger.error("Bad values: %s", ex.failure_cases)
    raise ValueError("Invalid schema.") from ex

# ---------------------------------------------------------------------------
# Fetch project members
# ---------------------------------------------------------------------------
def fetch_project_members(auth: INaturalistAuth, project_id: int) -> set:
    """
    Get the user IDs of all users in the iNaturalist project.
    Args:
        auth:
            iNaturalist authentication object
    Returns:
        Set of user IDs
    """
    url = f"https://api.inaturalist.org/v2/projects/{project_id}/members"
    headers = auth.get_auth_headers()

    # Make API requests
    all_results = page_requests(url, {}, headers, 100)

    # Extract user IDs from API response
    users = set()
    for result in all_results:
        try:
            user_id = int(result.get("user", {}).get("id"))
            users.add(user_id)
        except TypeError:
            logger.error("Invalid user ID response: %s", user_id)
    return users

# ---------------------------------------------------------------------------
# Fetch project annotations
# ---------------------------------------------------------------------------
def fetch_annotations(auth: INaturalistAuth) -> tuple[list[dict], list[dict]]:
    """
    Fetch all available annotations and annotation values from iNaturalist.

    iNaturalist annotations are stored as a pair of IDs representing a category (e.g. Life Stage) and 
    a value (e.g. Adult or Juvenile). The labels associated with these IDs are only available 
    throught iNaturalist's controlled terms API. This method is responsible for fetching the entire 
    list of controlled terms and returning them as categories and values, each with their respective
    labels.

    Args:
        auth: iNaturalist authentication object.
    Returns:
        (categories, values): Two lists of dictionaries, one for the annotation categories (e.g. 
            "Life Stage", "Alive or Dead") and one for the annotation values (e.g. "Adult",
            "Juvenile", "Alive", "Dead").
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

    # annotations = AnnotationOptions()
    categories = list()
    values = list()
    for result in results:
        annotation_id = result.get("id")
        annotation_category = {
            "annotation_id": annotation_id,
            "label": result.get("label")
        }
        categories.append(annotation_category)

        # Get values for this annotation
        annotation_values = result.get("values")
        if not annotation_values:
            raise ValueError(
                f"Annotation has no values. (ID={result.get('id')}, label={result.get('label')})"
            )
        for annotation_values in annotation_values:
            val = {
                "value_id": annotation_values.get("id"),
                "annotation_id": annotation_id,
                "label": annotation_values.get("label")
            }
            values.append(val)

    return categories, values


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def sliding_page_requests(url: str, params: dict, headers: dict) -> tuple[list, int]:
    """
    Helper function for paging through observation requests, using id_above instead of pages.

    Returns a tuple containing the results and the number of requests made.
    """
    all_results = []
    has_more = True
    iterations = 0

    # Make sure to clear "id_above" parameter
    params.pop("id_above", None)

    while has_more:
        response = requests.get(url, params, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])
        iterations += 1

        if not results:
            has_more = False
            time.sleep(1.0)
            break

        all_results.extend(results)

        last_id = results[-1].get("id")
        logger.debug("\tPage %i fetched. Last ID: %i. Total so far: %i.",
                     iterations, last_id, len(all_results))

        params["id_above"] = last_id

        time.sleep(1.0)

    return all_results, iterations


def page_requests(url: str, params: dict, headers: dict, per_page: int) -> list:
    """
    Helper function for paging through requests. Returns a list of results.
    """
    params["per_page"] = per_page
    all_results = []

    page = 1
    fail_count = 0
    while True:
        params["page"] = page
        try:
            response = requests.get(
                url=url,
                headers=headers,
                params=params,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            all_results.extend(results)
            time.sleep(0.5)

            if len(results) < per_page:
                break

            page += 1
            time.sleep(0.5)

        except requests.Timeout as ex:
            fail_count += 1
            logger.error("Request timed out.")
            if fail_count > 5:
                raise requests.exceptions.RequestException(
                    "Request timed out too many times."
                ) from ex

        except requests.exceptions.RequestException as ex:
            fail_count += 1
            logger.error("Encountered unknown exception: %s", str(ex))
            if fail_count > 5:
                raise requests.exceptions.RequestException(
                    "Recieved too many errors."
                ) from ex

    return all_results

