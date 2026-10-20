from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or backend/.env.

    Supabase is not provisioned yet (#2), so its fields are optional for now.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ACDOS Backend"
    supabase_url: str | None = None
    supabase_service_key: str | None = None


settings = Settings()
