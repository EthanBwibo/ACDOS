"""Runs accepted jobs in a process pool, off the event loop (#51).

A solve is pure Python and holds the GIL for its whole time limit; run on
the event loop, or in a thread, it would stall every other request for that
long. In a separate process it does not.

Job states: queued when accepted, running once a solver process takes it,
then completed or failed.
"""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from app.jobs import worker
from app.jobs.store import JobStore
from app.jobs.worker import PickupInput, SolveInput, VehicleInput
from app.solver.problem import Point

logger = logging.getLogger(__name__)

# Every job's task, held until it ends: the event loop keeps only a weak
# reference to tasks, so one nothing else refers to could be collected
# before it finishes.
_tasks: set[asyncio.Task] = set()


def solver_pool(size: int, travel_model: str) -> ProcessPoolExecutor:
    """Each process loads the travel model once when it starts (worker.init)."""
    return ProcessPoolExecutor(max_workers=size, initializer=worker.init, initargs=(travel_model,))


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        pool: Executor,
        pool_size: int,
        *,
        depot: Point,
        time_limit_sec: float,
        travel_model: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self._pool = pool
        # One slot per solver process. A job takes a slot before it is marked
        # running, so running means a process has it, not that it waits in
        # the pool's own queue.
        self._slots = asyncio.Semaphore(pool_size)
        self._depot = depot
        self._time_limit_sec = time_limit_sec
        self._travel_model = travel_model
        self.now = now

    def submit(
        self, job_id: UUID, pickups: tuple[PickupInput, ...], vehicles: tuple[VehicleInput, ...]
    ) -> None:
        task = asyncio.create_task(self._run(job_id, pickups, vehicles))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)

    async def _run(
        self, job_id: UUID, pickups: tuple[PickupInput, ...], vehicles: tuple[VehicleInput, ...]
    ) -> None:
        try:
            async with self._slots:
                await self.store.mark_running(job_id)
                job = SolveInput(
                    pickups,
                    vehicles,
                    self._depot,
                    # The plan starts now, not when the job was accepted:
                    # vans cannot leave while it waited in the queue.
                    epoch=self.now(),
                    time_limit_sec=self._time_limit_sec,
                    travel_model=self._travel_model,
                    # Fixed per job, so a job can be re-run to the same plan
                    # (when the generation cap, not the clock, stops it).
                    seed=job_id.int % 2**32,
                )
                loop = asyncio.get_running_loop()
                outcome = await loop.run_in_executor(self._pool, worker.run, job)
                await self.store.complete(job_id, outcome, self.now())
        except Exception as error:
            logger.exception("optimisation job %s failed", job_id)
            await self.store.fail(job_id, f"{type(error).__name__}: {error}")
