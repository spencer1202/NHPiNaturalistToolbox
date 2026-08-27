"""
This module provides models that define the configuration settings for each of the primary
functionalities of the tool. It also has a helper function that validates configurations.
"""
#### Standard imports ####
from typing import (
    Optional,
    Annotated,
    Type,
    TypeVar,
    Tuple
)
from pathlib import Path

#### Third-party imports ####
from pydantic import (
    BeforeValidator,
    BaseModel,
    StringConstraints,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def check_path(v: any, required: bool, check_exists: bool, extension: str = None) -> Optional[Path]:
    """
    Checks if the given file path fulfils the given requirements.

    Args:
        **v**: The filepath to check.
        **required**: If true, raise a ValueError if v is None or an empty string.
        **check_exists**: If true, the file must actually exist in the file system.
        **extension**: Make sure that the given file path has this extension (optional).
    
    Returns:
        The validated file path, or None if it's empty and required is false.
    
    Raises:
        ValueError if the file path does not pass the validation checks. 
    """
    # Handle missing, None, or blank strings from config file
    is_empty = v is None or (isinstance(v, str) and v.strip() == "")

    if is_empty:
        if required:
            raise ValueError("This file path is required.")
        return None

    path_obj = Path(v)

    # Check if the file actually exists
    if check_exists and not path_obj.exists():
        raise ValueError(f"Path does not exist: \'{v}\'")

    # Check for specific file extension
    if extension and path_obj.suffix.lower() != extension.lower():
        raise ValueError(f"File must use a \'{extension}\' extension.")

    return path_obj


def construct_error_message(err: ValidationError) -> list[str]:
    """
    Puts together a list of human readable error messages from a ValidationError.
    Args:
        err:
            ValidationError raised by a model constructor
        returns:
            A list of error strings
    """
    message = []
    for e in err.errors():
        field = e["loc"][0]
        code = e["type"]
        msg = e["msg"]
        message.append(f"Configuration error in field '{field}': {msg} (type={code})")
    return message


# ---------------------------------------------------------------------------
# Config validators
# ---------------------------------------------------------------------------

OptionalExistingCSV = Annotated[Optional[Path], BeforeValidator(
    lambda v: check_path(v, required=False, check_exists=True, extension=".csv")
)]
OptionalExistingFile = Annotated[Optional[Path], BeforeValidator(
    lambda v: check_path(v, required=False, check_exists=True)
)]
RequiredExistingCSV = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=True)
)]
RequiredNewFile = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=False)
)]
RequiredNewCSV = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=False, extension=".csv")
)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

# ---------------------------------------------------------------------------
# Config schemas
# ---------------------------------------------------------------------------

class CoreConfig(BaseModel):
    """
    Core configuration settings for the iNatDataPipeline tool.
    * **db_file**: File path of the local database.
    * **user_agent**: The HTTP user agent for this application.
    * **username**: The iNaturalist username to make authentications with.
    """
    db_file             : RequiredNewFile
    user_agent          : NonEmptyString
    username            : NonEmptyString


# Pydantic config schemas
class ObservationsConfig(BaseModel):
    """
    Configuration settings for fetching observations from the iNaturalist API.
    """
    place_id            : int
    quality_grade       : NonEmptyString
    per_page            : int
    batch_size          : int
    update_after_days   : int
    project_id          : int
    max_observations    : int


class TaxaConfig(BaseModel):
    """Model for taxon mapping command configurations"""
    tracking_list       : RequiredExistingCSV
    name_overrides_file : RequiredExistingCSV

class ReviewConfig(BaseModel):
    """Model for review command configurations"""
    experts_file            : RequiredExistingCSV
    experts_id_field        : str
    experts_expertise_field : str
    export_csv              : RequiredNewCSV


T = TypeVar('T', bound=BaseModel)

def validate_config(
        obj: dict,
        section_name: str = None,
        model_cls: Type[T] = None
) -> Tuple[CoreConfig, Optional[T]]:
    """
    Validate a config section.
    Arguments:
        obj:
            Dictionary containing the config objects (click context object)
        section_name:
            The name of the config section to load.
        model_cls:
            The pydantic config model to use to validate the config section.
    Returns:
        A validated model of the specified type.
    """

    if not section_name or not model_cls:
        raise ValueError("Missing section name or config model type!")

    section_data = obj.get(section_name, {})
    result = model_cls(**section_data)

    return result
