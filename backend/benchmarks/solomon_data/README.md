# Solomon VRPTW benchmark data (#13)

Benchmark instances for validating the GA-ALNS solver against published results. They are loaded by `benchmarks/solomon.py` and run by `benchmarks/solomon_harness.py`.

## Contents

| Path | What | Source |
|---|---|---|
| `instances/*.txt` | C101, R101–R112, RC101–RC108: 100 customers each, Solomon's text format | Solomon (1987); downloaded from SINTEF's mirror, `solomon-100.zip` |
| `solutions/*.txt` | The best-known solution for each instance (routes as customer numbers) | SINTEF TOP, each file credited to its authors in its header |
| `best_known.csv` | Best-known vehicles and distance per instance, with the reference SINTEF gives | SINTEF TOP |

The `.txt` files are byte-for-byte as downloaded (CRLF line endings, kept by `.gitattributes`). They were downloaded and the table read on 26 October 2026 from:
- https://www.sintef.no/projectweb/top/vrptw/100-customers/
- https://www.sintef.no/globalassets/project/top/vrptw/solomon/solomon-100.zip

The original instance page is http://web.cba.neu.edu/~msolomon/problems.htm.

**Instances:** R1 and RC1 are the sets #14 tunes against: random and semi-clustered customers with short horizons and tight windows. C101 is a sanity check: clustered customers, best-known 10 vehicles / 828.94, an easy target for any VRPTW heuristic.

## Conventions
- **Problem:** each customer has a demand, a service time and a window `[ready, due]` on the start of service. A vehicle that arrives early waits. Vehicles leave the depot no earlier than it opens and must be back by its due time. At most the instance's fleet (25) is used, each with the instance's capacity (200).
- **Distance and time:** the Euclidean distance between coordinates, kept at full double precision; travel time equals distance. Totals are rounded to 2 decimals only when reported. This is SINTEF's convention ("Distance and time should be calculated with double precision, total distance results are rounded to two decimals"). Some older published results used truncated distances and are not comparable.
- **Objective:** hierarchical. First minimise vehicles, then total distance. The best-knowns are ranked this way, and so are the solver's SOLOMON weights (`app/solver/weights.py`).
- **Check:** `tests/test_solomon.py` checks every file in `solutions/` with the harness's independent checker (`solomon.check_routes`). Each must be feasible and reproduce its row of `best_known.csv` exactly, to 2 decimals.
- **Truncated runs:** the harness can keep only customers 1 to n (`--customers 25`), the usual way of making the 25- and 50-customer versions. Their best-knowns are for a different objective and size, so such runs are reported as "no comparison", never against the 100-customer values.

## References
- Solomon, M. M. (1987). Algorithms for the vehicle routing and scheduling problems with time window constraints. *Operations Research*, 35(2), 254–265.
- SINTEF (n.d.). TOP: Solomon benchmark, 100 customers. Retrieved 26 October 2026, from https://www.sintef.no/projectweb/top/vrptw/100-customers/
- The best-known references per instance are in `best_known.csv`, as SINTEF lists them.
