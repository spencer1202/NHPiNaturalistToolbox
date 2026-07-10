# iNaturalist Data Pipeline ORBIC

A set of data aquisition and transformation tools for importing iNaturalist data into Biotics.

The aim is to provide an easy automated way to create mappings between tracking list taxon names and iNaturalist taxon names, download new observations, filter for records identified by experts, and transform the dataset into a format for import into Biotics. It maintains a file-based SQLite database to integrate the iNaturalist data with the Biotics tracking list, name overrides list, and list of experts.

This repository contains the data pipeline package and a name override cleaning script.

The code was adapted from the [iNatScraper repository](https://github.com/clark-hollenberg/iNatScraper) by Clark Hollenberg at CNHP and Kyle Kaskie at MTNHP.


## Install


## Usage


### Taxon Overrides
used to override search with better inat scientific name for creating mappings



inat_fields: JSON file with all of the fields to request for the observations API call