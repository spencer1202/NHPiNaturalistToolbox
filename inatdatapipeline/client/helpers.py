"""
This module contains some miscellaneous helper functions that interact with the iNaturalist API.
"""
import time
import logging
import requests

from inatdatapipeline.client.authentication import INaturalistAuth, TIMEOUT

logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)


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
    while has_more:
        response = requests.get(url, params, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if not results:
            has_more = False
            break

        all_results.extend(results)
        iterations += 1

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
