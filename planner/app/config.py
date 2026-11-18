from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    tz: str = "America/Los_Angeles"
    mealie_internal_url: str = "http://mealie:9000"
    mealie_public_url: str
    mealie_service_token: str
    session_secret: str
    database_url: str
    gemini_api_key: str = ""


settings = Settings()
