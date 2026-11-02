from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.solver.problem import JKIA


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The ACDOS project. Not a secret: the app ships it too. The backend
    # reads the project's public signing keys from it to check access tokens
    # (#52); without it, the endpoints that need a token answer 503.
    supabase_url: str | None = "https://yqqczlvhwlznvaezfpcl.supabase.co"
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
    # (docs/schema.md), so one base for all; a van on the road is left out
    # of a re-plan instead (#113). JKIA by default: the vans are based there, so
    # routes run JKIA -> pickups -> JKIA. Override with a base coordinate.
    depot_lat: float = Field(default=JKIA.lat, ge=-90, le=90)
    depot_lon: float = Field(default=JKIA.lon, ge=-180, le=180)
    # A van is on the road from its route's planned departure until its
    # planned arrival at JKIA plus this, unless the route is completed first
    # (#113). The margin covers a van running late; nothing reports its real
    # arrival yet.
    van_return_grace_min: float = Field(default=30.0, ge=0)


settings = Settings()
