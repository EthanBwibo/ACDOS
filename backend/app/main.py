from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import errors
from app.auth import JwksKeys, fetch_jwks, issuer
from app.body_limit import BodyLimit
from app.config import settings
from app.jobs import store
from app.jobs.runner import JobRunner, solver_pool
from app.routers import health, me, optimisation_jobs, pickup_events
from app.solver.problem import Point


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Token checking needs only the project URL (public keys). Tests install
    # their own keys; without a URL the #52 endpoints answer 503.
    if getattr(app.state, "jwt_keys", None) is None and settings.supabase_url:
        app.state.jwt_keys = JwksKeys(fetch_jwks(settings.supabase_url))
        app.state.jwt_issuer = issuer(settings.supabase_url)
    # Tests install their own runner; without a database there is none, and
    # the endpoints that need one answer 503.
    if getattr(app.state, "job_runner", None) is not None or not settings.database_url:
        yield
        return
    db = await store.connect(settings.database_url)
    pool = solver_pool(settings.solver_pool_size, settings.travel_model)
    try:
        app.state.db = db  # also read by the #52 endpoints (app/reads.py)
        depot = Point(settings.depot_lat, settings.depot_lon)
        job_store = store.PostgresJobStore(db, depot)
        # Safe only with one uvicorn process (README: --workers 1).
        await job_store.fail_unfinished()
        app.state.job_runner = JobRunner(
            job_store,
            pool,
            settings.solver_pool_size,
            depot=depot,
            time_limit_sec=settings.solve_time_limit_sec,
            travel_model=settings.travel_model,
        )
        yield
    finally:
        app.state.job_runner = None
        app.state.db = None
        pool.shutdown(wait=False, cancel_futures=True)
        await db.close()


# A constant, not a setting: the title is part of the committed contract
# (docs/openapi.json, #122), which must not depend on the environment.
app = FastAPI(title="ACDOS Backend", lifespan=lifespan)
errors.install(app)

app.include_router(health.router)
app.include_router(optimisation_jobs.router)
app.include_router(me.router)
app.include_router(pickup_events.router)
app.add_middleware(BodyLimit, limits={("POST", pickup_events.PATH): pickup_events.BODY_LIMIT})
