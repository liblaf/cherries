import pydantic_settings as ps


class BaseConfig(ps.BaseSettings):
    model_config = ps.SettingsConfigDict()
