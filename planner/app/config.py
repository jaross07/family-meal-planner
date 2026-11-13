from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    tz: str = "America/Los_Angeles"
    mealie_internal_url: str = "http://mealie:9000"
    mealie_public_url: str
    mealie_service_token: str
    session_secret: str
    database_url: str

    class Config:
        env_file = "../.env"
        extra = "ignore"


settings = Settings()
