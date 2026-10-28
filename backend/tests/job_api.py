"""Shared by the optimisation job API tests (#51)."""

import time
from uuid import UUID

from fastapi.testclient import TestClient

from app.solver.individual import Individual
from app.solver.problem import Problem

FINISHED = {"completed", "failed"}


def wait_for_job(client: TestClient, job_id: str, timeout_sec: float = 60.0) -> dict:
    """Poll GET until the job completes or fails, as the dispatcher's app would."""
    deadline = time.monotonic() + timeout_sec
    while True:
        body = client.get(f"/optimisation-jobs/{job_id}").json()
        if body["status"] in FINISHED:
            return body
        assert time.monotonic() < deadline, f"job {job_id} still {body['status']}"
        time.sleep(0.2)


def individual_from_result(problem: Problem, body: dict) -> Individual:
    """The plan the API returned, as the solver's Individual, so the shared
    feasibility check (tests/solver_checks.py) can judge it."""
    pickup_index = {UUID(p.id): i for i, p in enumerate(problem.pickups)}
    vehicle_index = {UUID(v.id): i for i, v in enumerate(problem.vehicles)}
    routes: list[list[int]] = [[] for _ in problem.vehicles]
    for route in body["routes"]:
        nodes = sorted(route["nodes"], key=lambda n: n["seq_order"])
        assert [n["seq_order"] for n in nodes] == list(range(1, len(nodes) + 1))
        routes[vehicle_index[UUID(route["vehicle_id"])]] = [
            pickup_index[UUID(n["pickup_request_id"])] for n in nodes
        ]
    unassigned = [pickup_index[UUID(i)] for i in body["unassigned"]]
    return Individual(routes, unassigned)
