"""
This module handles building a mapping between the Biotics and iNaturalist taxon entries.
"""

#!/usr/bin/env python3
#### Standard imports ####
import logging
from typing import Optional
import re
import time
from dataclasses import dataclass

#### Third-party imports ####
import requests
import pandas as pd

#### Local imports ####
from inatdatapipeline.client.authentication import INaturalistAuth, TIMEOUT
from inatdatapipeline.schemas.validation import TaxonMappingSchema

# Set up logging
logger = logging.getLogger('pipeline')

# Taxa requests URL
TAXA_URL = "https://api.inaturalist.org/v2/taxa"


@dataclass
class Taxon:
    """
    Object representing an iNaturalist taxon
    """
    taxon_id: int
    name: str


# ---------------------------------------------------------------------------
# Taxon Mapping Builder
# ---------------------------------------------------------------------------
class TaxonMappingBuilder:
    """
    This class is responsible for building a mapping between tracking list taxa and iNaturalist
    taxa. It contains static methods for preprocessing the tracking list, isolating taxa that 
    still need mappings, and building the mapping by requesting iNaturalist taxon names
    and IDs from the iNaturalist Taxa API endpoint.
    """
    @staticmethod
    def query_taxon(
        scientific_name: str,
        auth: INaturalistAuth,
        taxon_id: Optional[int] = None
    ) -> Optional[Taxon]:
        """
        Get taxon_id and matched name for a scientific name using iNaturalist API
        
        Args:
            scientific_name: The scientific name to look up
            taxon_id: iNaturalist taxon ID from overrides list if provided
            
        Returns:
            A Taxon object if a match is found, otherwise None.
        """
        # Set up parameters
        headers = auth.get_auth_headers()
        params = {
            "per_page"  : 5,
            "order"     : "desc",
            "order_by"  : "observations_count",
            "fields"    : ["name", "id"]
        }
        if taxon_id:
            params["taxon_id"] = taxon_id
        else:
            params["q"] = scientific_name

        # Make API request
        try:
            response = requests.get(TAXA_URL, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if not results:
                return None

        except requests.RequestException as ex:
            logger.error("Error looking up '%s': %s", scientific_name, str(ex))
            return None

        # Look for matching taxon in results
        taxon: Taxon                = None
        alternative: list[Taxon]   = []

        for result in results:
            result_name = result.get("name", "")
            result_id = result.get("id")

            # Convert result_id to an integer
            try:
                result_id_int = int(result_id)
            except (TypeError, ValueError):
                logger.error(
                    "Recieved invalid Taxon ID: '%s'. Skipping malformed result.", result_id)
                continue

            # Handle NaN values and ensure we have valid data
            if (
                pd.isna(result_name)
                or pd.isna(result_id_int)
                or not result_name
                or not result_id_int
            ):
                logger.debug(
                    "Recieved invalid response data while searching for '%s': (%s, %s)", 
                    str(taxon_id) if taxon_id else scientific_name,
                    str(result_name),
                    str(result_id)
                )
                continue

            if (
                (taxon_id and result_id_int == taxon_id)                # taxon ID match
                or (result_name.lower() == scientific_name.lower())     # name exact match
            ):
                taxon = Taxon(result_id_int, result_name)
                break

            # Keep track of first alternative option
            if not alternative:
                alternative = Taxon(result_id_int, result_name)

        # No exact matches found
        if not taxon and alternative:
            taxon = alternative

        return taxon


    @staticmethod
    def _preprocess_names(name: str) -> str:
        """
        Preprocess taxon name for iNaturalist API query by converting trinomial format
        
        Converts names like "Aster alpinus var. vierhapperi" to "Aster alpinus vierhapperi"
        which is the preferred format for iNaturalist queries.
        
        Args:
            name: Scientific name to preprocess
            
        Returns:
            Name with "var.", "pop.", and "ssp." removed for better iNaturalist matching
        """
        if not name or pd.isna(name):
            return None

        # Edge case: name is a single-word string, return name as is
        is_single_word = re.fullmatch(r"^[A-Za-z\-]+", name.strip())
        if is_single_word:
            logger.warning("Encountered single-word taxon name '%s' - marking as undescribed.", name.strip())
            return name.strip()

        # Regular expression that extracts the genus name, species name, and subspecies name or
        # subspecies/population number.
        expr = r"^((?:[a-zA-Z\-]+[ \t]){1,2})(?:(?:var\.|pop\.|ssp\.|sp\.)\s)?(.+)?"
        match = re.search(expr, name.strip())
        if not match:       # some weird edge case
            return None

        processed_name = match.group(1) + match.group(2)

        # Clean up any double spaces
        while "  " in processed_name:
            processed_name = processed_name.replace("  ", " ")

        return processed_name.strip()


    @staticmethod
    def preprocess_tracking_df(
        tracking_df: pd.DataFrame,
        overrides_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Preprocesses tracking dataframe. Creates a new column called 'search_name' that contains a 
        clean version of the scientific name, or the name override if it exists. For undescribed
        taxa, 'search_name' is replaced with the generic taxon name. Adds another column called 
        'is_described' that is true for undescribed taxa and false otherwise.

        Args:
            tracking_df: Dataframe with tracked taxa. Should follow the TrackingSchemaClean model.
            overrides_df: Dataframe with name overrides. Should follow the OverridesSchema model.
        
        Returns:
            A copy of the tracking dataframe that has been preprocessed.
        """
        tracking_df = tracking_df.copy()

        # Insert override names
        tracking_df["search_name"] = (
            tracking_df["est_id"]
            .map(overrides_df.set_index("est_id")["inat_name"])
        )
        overrides_count = len(tracking_df[tracking_df["search_name"].notna()])
        logger.debug("* Inserted %i overrides.", overrides_count)

        # Load search name column with remaining names
        tracking_df["search_name"] = tracking_df["search_name"].fillna(tracking_df["sci_name"])

        # Preprocess names
        tracking_df["search_name"] = (
            tracking_df["search_name"].apply(TaxonMappingBuilder._preprocess_names)
        )

        # Add generic names
        undescribed_names = TaxonMappingBuilder.get_undescribed_names(tracking_df["search_name"])
        is_described_mask = undescribed_names == ""
        tracking_df["is_described"] = is_described_mask
        tracking_df.loc[~is_described_mask, "search_name"] = undescribed_names

        undescribed_count = len(tracking_df[~tracking_df["is_described"]])
        logger.debug("* Updated %i undescribed taxon names.", undescribed_count)

        return tracking_df


    @staticmethod
    def get_undescribed_names(names: pd.Series) -> pd.Series:
        """
        Extracts generic names for all undescribed taxa and returns them as a series.
        Args:
            names: Series of taxon names.

        Returns:
            A series that is populated by generic names for all undescribed taxa.

        """
        names = names.copy()

        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+)\d+$"
        result = names.str.extract(expr, expand=False).str.strip()

        # Second pass to check for single-word names
        is_single_word = names.str.fullmatch(r"[A-Za-z\-]+").fillna(False)
        result = result.fillna(names.where(is_single_word)).infer_objects(copy=False)

        return result.fillna("")


    @staticmethod
    def get_new_mappings(
        auth: INaturalistAuth,
        to_match: pd.DataFrame,
        override_map: dict = None
    ) -> tuple[pd.DataFrame, int]:
        """
        Get taxon mappings by querying for the taxa in the provided dataframe. Structures responses
        into dataframes and validates them.

        Args:
            auth: 
                An iNaturalist authentication object.
            to_match: 
                Dataframe of tracking list taxa to be mapped to their iNaturalist counterparts.
            override_map: 
                A possibly empty dictionary that maps tracking list taxa by their est_id to 
                iNaturalist taxon_ids, which will be used to perform the search instead of the
                taxon's name.

        Returns:
            (mappings_df, request_count):
                A dataframe of mappings between Biotics taxa and iNaturalist taxa, and the number
                of requests made.
        """
        if override_map is None:
            override_map = {}

        # Process unmatched rows
        process_total = len(to_match)
        process_num = 1
        request_count = 0
        new_taxa = []
        undescribed_names: dict[str, Taxon] = {}

        for _, row in to_match.iterrows():
            taxon: Taxon = None
            search_name = row["search_name"]
            override_id = override_map.get(row["est_id"])   # override taxon ID

            logger.info(
                "%4i / %i\t%s %s",
                process_num,
                process_total,
                search_name,
                ("(%s)" % row["sci_name"]) if row["sci_name"] != search_name else ""
            )

            # Check if this is an undescribed taxon, and if so if it has already been mapped.
            if row["is_described"]:
                taxon = TaxonMappingBuilder.query_taxon(search_name, auth, override_id)
                request_count += 1
                logger.debug("* Request count: %s", request_count)
            else:
                undescribed_taxon = undescribed_names.get(search_name)
                if not undescribed_taxon:
                    taxon = TaxonMappingBuilder.query_taxon(search_name, auth, override_id)
                    # Cache placeholder taxon if no result found
                    undescribed_names[search_name] = taxon if taxon else Taxon(0, "N/A") 
                    request_count += 1
                    logger.debug("* Request count: %s", request_count)
                else:
                    taxon = undescribed_taxon

            # No result found
            if not taxon or not taxon.taxon_id:
                logger.debug("* No result found.")
            else:
                logger.debug("* Result found: name=%s, taxon_id=%i", taxon.name, taxon.taxon_id)
                new_taxon = row.to_dict() # Copy all existing fields from to_match row
                new_taxon["taxon_id"] = taxon.taxon_id # Add / overwrite mapping fields
                new_taxon["inat_name"] = taxon.name
                new_taxa.append(new_taxon)

            # Be kind to the API
            time.sleep(1)
            process_num += 1

        if len(new_taxa) == 0:
            return pd.DataFrame(), request_count
        return pd.DataFrame(new_taxa), request_count


    @staticmethod
    def build_override_id_map(overrides_df: pd.DataFrame) -> dict[int, int]:
        """
        Builds a dictionary that maps est_ids to override ids from an overrides dataframe.
        
        Args:
            overrides_df: Dataframe of overrides that conforms to the OverridesSchema.
        
        Returns:
            Dictionary that maps each est_id to its corresponding taxon id override from the
            dataframe.
        """
        just_override_ids = overrides_df.dropna(subset=["taxon_id"])
        return dict(zip(just_override_ids["est_id"], just_override_ids["taxon_id"]))


    @staticmethod
    def get_to_match(tracking_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
        """
        Puts together a dataframe with just the taxa that need to be searched for, excluding
        existing mappings if any are present.

        Args:
            tracking_df: Dataframe with tracking list that conforms to the TrackingSchemaClean
            model, including the search_name and is_described columns.
            mapping_df: Dataframe with existing mappings which conforms to the TaxonMappingSchema
            model.
        
        Returns:
            A pared down copy of the tracking dataframe with just taxon that need to be searched 
            for and these columns: sci_name, search_name, est_id, is_described.
        """
        if tracking_df is None or len(tracking_df) == 0:
            raise ValueError("Tracking dataframe must not be None or empty.")

        # Create mapping dataframe, either with prior entries or from scratch
        if mapping_df is None:
            mapping_df = TaxonMappingSchema.empty()

        logger.debug("Filtering for taxa that don't have mappings yet...")
        match_mask = tracking_df["est_id"].isin(mapping_df["est_id"])
        needed_cols = ["sci_name", "search_name", "est_id", "is_described"]
        to_match = tracking_df.loc[~match_mask, needed_cols].copy()

        return to_match
