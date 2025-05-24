import pydantic_settings as ps


class BaseConfig(ps.BaseSettings):
    model_config = ps.SettingsConfigDict(cli_parse_args=True)
    # TODO: add support for config files
