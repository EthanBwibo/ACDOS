"""A solver process exits on its own when the API process dies (#51).

A graceful shutdown stops the pool; a hard kill does not, and without
worker._exit_with the pool's processes ran on as orphans (seen in the #51
smoke run on Windows).
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

from app.jobs.processes import Process

BACKEND = Path(__file__).resolve().parents[1]

# Stands in for the API process: starts a one-process pool, makes it spawn
# its solver process, reports that process's PID, then waits to be killed.
PARENT = """
import os, time
from app.jobs.runner import solver_pool

if __name__ == "__main__":
    pool = solver_pool(1, "haversine")
    print(pool.submit(os.getpid).result(), flush=True)
    time.sleep(120)
"""


def test_solver_process_exits_when_its_parent_is_killed():
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT], cwd=BACKEND, stdout=subprocess.PIPE, text=True
    )
    try:
        solver = Process(int(parent.stdout.readline()))
    except BaseException:
        parent.kill()
        raise

    parent.kill()  # hard: TerminateProcess on Windows, SIGKILL elsewhere
    parent.wait()

    exited = solver.wait(timeout_sec=10)
    if not exited:
        os.kill(solver.pid, signal.SIGTERM)  # don't leave it behind
    assert exited, "the solver process outlived its parent"
