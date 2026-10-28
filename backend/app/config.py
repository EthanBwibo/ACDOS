from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ACDOS Backend"
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    # Postgres connection for the optimisation job API (#51), for example
    # Supabase's session pooler (port 5432). The backend connects as the
    # postgres role, which bypasses RLS. Without it, the job endpoints
    # answer 503.
    database_url: str | None = None

    # Seconds each optimisation runs for. Long enough for the GA to improve on
    # its first population, short enough for a dispatcher to wait on.
    solve_time_limit_sec: float = Field(default=15.0, gt=0)
    # Solver processes, and so jobs that run at once; the rest queue.
    solver_pool_size: int = Field(default=2, ge=1)
    # "rf": the Random Forest and zone matrix (#108); "haversine": straight
    # lines at 30 km/h, for tests.
    travel_model: str = "rf"
    # Where every vehicle starts. vehicles has no location column
    # (docs/schema.md), so one depot until re-planning (#113) starts vans
    # from where they are.
    depot_lat: float = Field(default=-1.30, ge=-90, le=90)
    depot_lon: float = Field(default=36.80, ge=-180, le=180)


settings = Settings()
