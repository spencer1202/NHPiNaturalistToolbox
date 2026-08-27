"""
This module contains the INaturalistAuth class which takes care of getting authentication for 
iNaturalist requests.
"""
#### Standard imports ####
import getpass
import os
import logging
from typing import Optional

#### Third-party imports ####
import keyring
import requests
KEYRING_KEY = "/inaturalist"

#### Constants ####
TIMEOUT = 30

#### Setup ####
logger = logging.getLogger('pipeline')

env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# ---------------------------------------------------------------------------
# iNaturalist Authentication
# ---------------------------------------------------------------------------
class INaturalistAuth:
    """
    Helper class that handles getting iNaturalist access tokens and request headers.
    """
    def __init__(self, user_agent: str = "iNat_ORBIC_DataPipeline/1.0"):
        self.user_agent: str = user_agent
        self.access_token: str = None       # OAuth token
        self.jwt: str = None                # JWT for v2 API

    def _get_oauth_token(self, user: str, password: str) -> str:
        """Get an OAuth token directly. Raises ValueError if request fails."""
        response = requests.post(
            "https://www.inaturalist.org/oauth/token",
            data={
                "client_id"     : os.environ["INAT_APP_ID"],
                "client_secret" : os.environ["INAT_APP_SECRET"],
                "grant_type"    : "password",
                "username"      : user,
                "password"      : password,
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()
        token = response.json().get("access_token")

        return token


    def _get_credentials(self, user: str) -> str:
        """Prompt for a password, save it to the keyring, and return it"""
        print(f"Enter your iNaturalist password for {user}:")
        password = getpass.getpass()
        keyring.set_password(KEYRING_KEY, user, password)
        print("Credentials saved for future use.")
        return password


    def generate_access_token(self, user: str) -> str | None:
        """
        Fetches iNaturalist authorization access token using credentials from the system keyring. 
        Raises ValueError if credentials not present.
        """
        # Try to load app secret and ID from environment
        if (
            not os.getenv("INAT_APP_ID")
            or not os.getenv("INAT_APP_SECRET")
        ):
            msg = "No iNaturalist App ID or App Secret found in environment variables."
            raise ValueError(msg)

        password = keyring.get_password(KEYRING_KEY, user)

        try:
            self.access_token = self._get_oauth_token(user, password)
        except requests.HTTPError as ex:
            raise ValueError(f"Failed to authenticate credentials for {user}.") from ex

        if not self.access_token:
            raise ValueError(f"Failed to obtain OAuth token for user '{user}'")

        self.jwt = self._get_jwt(self.access_token)
        return self.access_token

    def _get_jwt(self, oauth_token: str) -> Optional[str]:
        """Exchange an OAuth access token for a JWT (required for v2 API)"""
        response = requests.get(
            "https://www.inaturalist.org/users/api_token",
            headers={
                "Authorization": f"Bearer {oauth_token}"
            },
            timeout=TIMEOUT
        )
        if not response.ok:
            raise ValueError(
                f"JWT exchange failed: HTTP {response.status_code}\n{response.text[:500]}"
            )
        try:
            return response.json().get("api_token")
        except requests.exceptions.JSONDecodeError as ex:
            raise ValueError(
                f"JWT endpoint returned non-JSON response:\n{response.text[:500]}"
            ) from ex

    def get_access_token(self) -> str:
        """Get this object's access token if generated"""
        return self.access_token


    def get_auth_headers(self):
        """Get authentication headers for API requests"""
        if not self.jwt:
            return None

        headers = {}
        headers["User-Agent"] = self.user_agent
        headers["Authorization"] = f"Bearer {self.jwt}"
        return headers
