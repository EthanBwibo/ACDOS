import random

from app.solver.instances import smoke_30
from benchmarks.demo_solve import run


def test_the_class_demo_runs_on_the_smoke_instance(capsys):
    run(smoke_30(), random.Random(0), time_limit_sec=2.0)

    printed = capsys.readouterr().out
    assert "Nearest neighbour" in printed
    assert "GA-ALNS" in printed
    assert "ride_over_cap=" in printed
    assert "Routes" in printed
