from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Base class for experiment configuration models.

    Subclass `BaseConfig` when an experiment callable should receive structured
    settings. [`main`][liblaf.cherries.main] instantiates missing annotated
    arguments, logs Pydantic models as parameters, and then calls the
    experiment.

    Examples:
        >>> class Config(BaseConfig):
        ...     name: str = "world"
        ...     epochs: int = 3
        >>> Config.model_fields["name"].default
        'world'
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        cli_parse_args=True, cli_kebab_case=True
    )
