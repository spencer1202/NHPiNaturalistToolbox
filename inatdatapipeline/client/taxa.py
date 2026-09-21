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

URL = "https://api.inaturalist.org/v2/taxa"

CLASS_LEVEL_MAP = {
    "Species"       : "species",
    "Population"    : "hybrid,subspecies,variety,form",
    "Variety"       : "hybrid,subspecies,variety,form",
    "Subspecies"    : "hybrid,subspecies,variety,form",
    "Genus"         : "genus"
}
BIOTICS_SUBRANKS = ["Population", "Variety", "Subspecies"]


@dataclass
class Taxon:
    """
    An object representing an iNaturalist taxon and its mapping to a tracking list taxon.
    """
    taxon_name      : str = None
    taxon_id        : int = None
    est_id          : int = None
    parent_egt_id   : int = None
    genus_egt_id    : int = None

    def get_mapping_record(self):
        return {
            "inat_name"         : self.taxon_name,
            "taxon_id"          : self.taxon_id,
            "est_id"            : self.est_id,
            "parent_egt_id"     : self.parent_egt_id,
            "genus_egt_id"      : self.genus_egt_id
        }


# ---------------------------------------------------------------------------
# Taxon Mapping Builder
# ---------------------------------------------------------------------------
class TaxonMappingBuilder:
    # TODO update docstring
    """
    This class is responsible for building a mapping between tracking list taxa and iNaturalist
    taxa. It contains static methods for preprocessing the tracking list, isolating taxa that 
    still need mappings, and building the mapping by requesting iNaturalist taxon names
    and IDs from the iNaturalist Taxa API endpoint.
    """
    def __init__(self, auth: INaturalistAuth):
        self.auth: INaturalistAuth = auth
        self.request_count: int = 0
        self.process_count: int = 0
        self.process_total: int = 0
        self.error_count: int = 0

    def _make_taxon_request(self, search_name: str, classification_level: str = None, override_id: int = None):
        """
        Perform iNaturalist taxa API search for search_name. Ignores search_name in favor of override_id
        if one is provided.

        Args:
            search_name: Taxon name to search for.
            classification_level: Taxonomic rank filter for taxon search. Options are 'Species', 
                'Population', 'Variety', 'Subspecies', and 'Genus'.
            override_id: iNaturalist taxon ID to search for, overriding the search_name.
        
        Returns:
            results: API results dictionary.
        """
        headers = self.auth.get_auth_headers()
        if headers is None:
            logger.warning("Could not retrieve iNaturalist authentication.")

        params = {
            "per_page"  : 10,
            "order"     : "desc",
            "order_by"  : "observations_count",
            "fields"    : ["name", "id", "matched_term"]
        }

        if classification_level:
            params["rank"] = CLASS_LEVEL_MAP.get(classification_level)
        
        if override_id:
            params["taxon_id"] = override_id
        else:
            params["q"] = search_name

        try:
            response = requests.get(URL, params, headers=headers)
            self.request_count = self.request_count + 1
            response.raise_for_status()
        except requests.RequestException as ex:
            self.error_count = self.error_count + 1
            logger.error("Query search failed: %s (Error count = %i)", str(ex), self.error_count)
            if self.error_count >= 5:
                raise ValueError("Too many errors, aborting search")
            
            time.sleep(1)
            return None

        data = response.json()
        results = data.get("results")
        time.sleep(1)

        return results

    @staticmethod
    def _select_matching_name(search_name: str, results: dict, subrank_name: str = None) -> tuple[Optional[str], Optional[int]]:
        """
        Select the best match for search_name from the API results.
        """
        if results is None or len(results) == 0:
            raise ValueError("No results to select match from!")

        # alternative = None
        taxon = None
        for result in results:
            result_name = result["name"]
            if (result_name == search_name or (subrank_name and result_name == subrank_name)):
                taxon = result_name, result["id"]
                break
            
            if taxon is None and (
                (
                    result["matched_term"] == search_name
                    or (subrank_name and result["matched_term"] == subrank_name)
                )
            ):
                taxon = result_name, result["id"]
                
            # if not alternative:
                # alternative = result

        if taxon:
            return taxon
        
        # if alternative:
            # return alternative["name"], alternative["id"]

        return None, None

    @staticmethod
    def _select_matching_id(search_id: int, results: int) -> tuple[Optional[str], Optional[int]]:
        """
        Select the result with a taxon ID matching search_id.
        """
        if results is None or len(results) == 0:
            raise ValueError("No results to select match from!")

        taxon = None
        for result in results:
            if result["id"] == search_id:
                taxon = result["name"], result["id"]
                break

        return taxon if taxon else (None, None)
    

    def _search_all_ranks(self, record: dict, searched_set: set) -> Taxon | None:
        """
        Searches for a taxon and extracts a match from the results, starting at its current classification level and 
        recursively searching the taxon's higher levels until either a result is found, or the search at the genus level 
        returns no results. The classification levels in order are subrank (subspecies, population, or variety), species, 
        and genus.
        
        Skips searching for undescribed taxa at their current rank and starts with the rank above. Also skips searching
        for names that are already present in ``searched_set``.
        
        Args:
            record: A single entry from a cleaned, preprocessed tracking list.
            searched_set: The set of taxon names which have already been searched for. This set is mutated to add each
                name searched for.
            
        Returns:
            A Taxon object with either est_id, parent_est_id, or genus_est_id populated with the corresponding ID from
            ``record``, depending on what kind of search produced a match.
        """
        if record["is_described"]:
            return self._search_all_ranks_r(record, searched_set, "normal")
        
        # Skip to next classification level for undescribed names
        logger.debug(" " * 14 + f"Skipping undescribed taxon: { record['sci_name_clean'] }")
        # Search for parent if this is a subrank, otherwise search for genus
        if record["classification_level"] in BIOTICS_SUBRANKS:
            return self._search_all_ranks_r(record, searched_set, "parent")
        return self._search_all_ranks_r(record, searched_set, "genus")


    def _search_all_ranks_r(self, record: dict, searched_set: set, search_type: str) -> Taxon | None:
        """
        Recursively searches for a taxon until a result is found or the search at the genus level returns no results.
        See search_all_ranks for more details.
        """
        # Keep track of subrank name when searching for parent
        subrank_name: str = None

        match search_type:
            case "normal":
                name = record["sci_name_clean"]
                classification_level = record["classification_level"]
                id_field = "est_id"
                
            case "parent":
                id_field = "parent_egt_id"
                name = record["parent_sci_name"]
                classification_level = "Species"
                subrank_name = record["sci_name_clean"]

            case "genus":
                id_field = "genus_egt_id"
                name = record["genus_sci_name"]
                classification_level = "Genus"

            case _:
                raise ValueError(f"Invalid search type: {search_type}")

        logger.debug(" " * 14 + f"{search_type.upper()}: {name} ({classification_level})")

        if name in searched_set:
            logger.debug(" " * 14 +"Already searched for!")
            return None
        searched_set.add(name)
 
        results = self._make_taxon_request(name, classification_level)

        if results:
            names = [result["name"] for result in results]
            logger.debug(" " * 14 +f"Results found: {names}")
            match_name, match_id = self._select_matching_name(name, results, subrank_name)

        if not results or not match_name:
            logger.debug(" " * 14 +f"No result or no matches")
            match search_type:
                case "genus":
                    return None
                case "normal":
                    # This is subrank, search by parent species
                    if record["parent_sci_name"]:
                        logger.debug(" " * 14 +"Taxon has parent species!")
                        return self._search_all_ranks_r(record, searched_set, "parent")
                    else:
                        return self._search_all_ranks_r(record, searched_set, "genus")
                case "parent":
                    return self._search_all_ranks_r(record, searched_set, "genus")

        taxon = Taxon(match_name, match_id)
        setattr(taxon, id_field, record[id_field])

        return taxon


    def _search_override(self, override_name: str, est_id: int, override_id: int) -> Taxon | None:
        logger.info(" " * 14 + f"OVERRIDE: {override_name}{(' (%s)' % override_id) if override_id else ''}")
        result = self._make_taxon_request(override_name, None, override_id)
        if result:
            if not override_id:
                match_name, match_id = self._select_matching_name(override_name, result)
            else:
                match_name, match_id = self._select_matching_id(override_id, result)
                pass

        if not result or not match_name:
            return None
        
        return Taxon(match_name, match_id, est_id)
    

    @staticmethod
    def _preprocess_name(name: str) -> str:
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
    def _fill_parent(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        subrank_mask = df["classification_level"].isin(BIOTICS_SUBRANKS)

        parent_egt_id = df["parent_egt_id"].copy()
        parent_sci_name = df["parent_sci_name"].astype(object)

        parent_egt_id.loc[subrank_mask] = parent_egt_id.loc[subrank_mask].fillna(df.loc[subrank_mask, "egt_id"])
        parent_sci_name.loc[subrank_mask] = parent_sci_name.loc[subrank_mask].fillna(df.loc[subrank_mask, "global_sci_name"])

        return parent_egt_id, parent_sci_name


    @staticmethod
    def _get_undescribed_names(names: pd.Series) -> pd.Series:
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
    def preprocess_tracking_df(
        tracking_df: pd.DataFrame,
        overrides_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Preprocesses tracking dataframe. Creates new columns override_name and sci_name_clean and
        cleans both, adds is_undescribed column, and fills in parent_egt_id and parent_sci_name
        where it's needed.

        Args:
            tracking_df: Dataframe with tracked taxa. Should follow the TrackingSchemaClean model.
            overrides_df: Dataframe with name overrides. Should follow the OverridesSchema model.
        
        Returns:
            A copy of the tracking dataframe that has been preprocessed.
        """
        tracking_df = tracking_df.copy()

        # Insert override names
        tracking_df["override_name"] = (
            tracking_df["est_id"]
            .map(overrides_df.set_index("est_id")["inat_name"])
        )
        overrides_count = len(tracking_df[tracking_df["override_name"].notna()])
        logger.debug("* Inserted %i overrides.", overrides_count)

        # Preprocess names
        tracking_df["sci_name_clean"] = (
            tracking_df["sci_name"].apply(TaxonMappingBuilder._preprocess_name)
        )
        tracking_df["override_name"] = (
            tracking_df["override_name"].apply(TaxonMappingBuilder._preprocess_name)
        )

        # Mark undescribed taxa
        undescribed_names = TaxonMappingBuilder._get_undescribed_names(tracking_df["sci_name_clean"])
        is_described_mask = undescribed_names == ""
        tracking_df["is_described"] = is_described_mask

        undescribed_count = len(tracking_df[~tracking_df["is_described"]])
        logger.debug("* Identified %i undescribed taxon names.", undescribed_count)

        (
            tracking_df["parent_egt_id"], 
            tracking_df["parent_sci_name"]
        ) = TaxonMappingBuilder._fill_parent(tracking_df)

        return tracking_df


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
        # needed_cols = ["sci_name", "override_name", "search_name", "est_id", "is_described"]
        needed_cols = [
            "sci_name",
            "sci_name_clean",
            "est_id",
            "override_name",
            "is_described",
            "classification_level",
            "parent_egt_id",
            "parent_sci_name",
            "genus_sci_name",
            "genus_egt_id"
        ]
        to_match = tracking_df.loc[~match_mask, needed_cols].copy()

        return to_match


    def create_new_mappings(
            self,
            tracking_df: pd.DataFrame,
            override_map: dict
    ) -> pd.DataFrame:
        """
        Creates mappings between the taxa in tracking_df and their corresponding iNaturalist taxon.

        Args:
            tracking_df: A tracking list dataframe that conforms to validation.TrackingSchemaClean.
            override_map: A dictionary that maps taxon est_ids to manually entered iNaturalist 
                taxon IDs. Created with TaxonMappingBuilder.build_override_id_map.
        
        Returns:
            mappings_df: A dataframe populated with mappings between Biotics taxa and iNaturalist
                taxa. Each entry is a mapping between an iNaturalist taxon and either a taxon's own
                est_id, the egt_id of its parent species, or the egt_id of its genus.
        """
        new_mappings = []
        searched_set = set()
        self.process_count = 0
        self.error_count = 0
        self.process_total = len(tracking_df)

        # Make sure auth token is generated
        if not self.auth.get_access_token():
            self.auth.generate_access_token()
        self.request_count = self.request_count + 1
        
        for record in tracking_df.to_dict(orient="records"):
            # Log progress
            self.process_count = self.process_count + 1
            progress = f"[{self.process_count:>4} / {self.process_total}]"
            msg = f"{progress:<13} {record['sci_name']}"
            logger.info(msg)

            if record["override_name"] or override_map.get(record["est_id"]):
                taxon = self._search_override(record["override_name"], record["est_id"], override_map.get(record["est_id"]))
            else:
                taxon = self._search_all_ranks(record, searched_set)

            if taxon is not None:
                logger.debug(" " * 14 + f"MATCH: {taxon}")
                new_mappings.append(taxon.get_mapping_record())
            else:
                logger.debug(" " * 14 +"NO MATCH")
            logger.debug("")

        mappings_df = pd.DataFrame(new_mappings)
        return mappings_df
    
