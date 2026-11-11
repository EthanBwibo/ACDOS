GA-ALNS, seeds 1 to 10, only the time limit ends a run. 60 s: #203's runs. 300 s: this issue's. NV vehicles, TD distance (Solomon's check); best-known from SINTEF.

| Instance | Best-known NV / TD | NV 60 s | NV 300 s | NV gap closed | TD 60 s | TD 300 s | TD gap % 60 s | TD gap % 300 s | Best 60 s | Best 300 s | Generations 60 / 300 | Feasible 60 / 300 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R101 | 19 / 1650.80 | 19.8 | 19.3 | 62% | 1787.0 | 1694.8 | +8.3 | +2.7 | 19 / 1783.5 | 19 / 1676.6 | 46 / 253 | 10 / 10 of 10 |
| R105 | 14 / 1377.11 | 16.0 | 15.0 | 50% | 1548.9 | 1420.6 | +12.5 | +3.2 | 15 / 1516.9 | 15 / 1380.0 | 43 / 228 | 10 / 10 of 10 |
| RC101 | 14 / 1696.95 | 16.4 | 15.9 | 21% | 1771.8 | 1728.2 | +4.4 | +1.8 | 15 / 1820.6 | 15 / 1780.3 | 46 / 236 | 10 / 10 of 10 |
| RC105 | 13 / 1629.44 | 15.9 | 15.5 | 14% | 1728.2 | 1609.7 | +6.1 | -1.2 | 15 / 1660.8 | 15 / 1575.6 | 44 / 225 | 10 / 10 of 10 |

300 s minus 60 s, paired by seed: Wilcoxon signed-rank, Holm across the four instances within each metric (* below 0.05). Better / tied / worse: 300 s's record.

| Instance | NV mean change | NV better / tied / worse | NV p | TD mean change | TD better / tied / worse | TD p |
|---|---|---|---|---|---|---|
| R101 | -0.50 | 5/5/0 | 0.1875 | -92.22 | 10/0/0 | 0.0078 * |
| R105 | -1.00 | 9/1/0 | 0.0156 * | -128.29 | 10/0/0 | 0.0078 * |
| RC101 | -0.50 | 5/5/0 | 0.1875 | -43.67 | 8/0/2 | 0.0645 |
| RC105 | -0.40 | 4/6/0 | 0.1875 | -118.44 | 10/0/0 | 0.0078 * |

## Notes

Run overnight on 11 November 2026, right after #210 on the same quiet machine: 40 runs of 300 s, 3 h 20 min. All 40 runs were feasible on Solomon's checker.

- **Distance closes most of the way:** at 300 s, the mean distance is within 1.8 to 3.2% of best-known on three instances, against 4.4 to 12.5% at 60 s. The best R101 run is 1.6% off, at 19 vans, which is the best-known count.
- **RC105's mean distance is below best-known (−1.2%),** but that is not a better solution. It uses 15.5 vans on average against best-known's 13, and Solomon ranks vans first. More vans can always drive less.
- **Vans improve less.** The mean drops on every instance, by 0.4 to 1.0 van. But the best run's count is the same at 60 s and 300 s on all four (19, 15, 15, 15), so the extra time brings more seeds to the best count rather than finding a smaller one. Best-known's count is never reached on R105, RC101 or RC105. Only R105's van change is significant after Holm: 9 of 10 seeds dropped a van.
- **No run got worse.** Every seed's 300 s cost is at most its 60 s cost, consistent with one search seen later. RC101's two seeds with a longer distance at 300 s (3 and 7) each dropped a van, which is the hierarchy at work.
- **Three distance p values sit at the floor:** with 10 seeds, the smallest signed-rank p is 2/1024. Holm across four makes that 0.0078. RC101's distance (0.0645) misses because of those two seeds.
- **Generations:** about 5.4 times as many (225 to 253, against 43 to 46). That's in line with five times the time.
- **For Chapter 5:**
  - GA-ALNS's distance gap at 60 s is mostly a time budget, not a ceiling.
  - Its van gap on R105, RC101 and RC105 needs more than time. Plausibly it needs a route-elimination operator, which the solver doesn't have.
