450 runs, 10 seeds per instance and method. Only the time limit ends a run: early stopping and the generation cap are off for every method.
Runs with a pickup lost or duplicated, or that Solomon's check rejects: 10.

**Plain GA against GA-ALNS.**

| Instance | Cost plain_ga | Cost ga_alns | Vans plain_ga | Vans ga_alns | Distance plain_ga | Distance ga_alns | Late plain_ga | Late ga_alns | Unassigned plain_ga | Unassigned ga_alns | Generations plain_ga | Generations ga_alns |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R101 | 52,002,502,022 | 1,981,787 | 25.0 | 19.8 | 2021.8 | 1787.0 | 0.0 | 0.0 | 5.2 | 0.0 | 1872 | 46 |
| R102 | 2,351,965 | 1,811,607 | 23.5 | 18.1 | 1964.8 | 1607.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1868 | 47 |
| R103 | 1,831,650 | 1,511,401 | 18.3 | 15.1 | 1650.1 | 1401.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1923 | 44 |
| R104 | 1,471,363 | 1,201,194 | 14.7 | 12.0 | 1363.0 | 1194.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2002 | 39 |
| R105 | 2,241,968 | 1,601,549 | 22.4 | 16.0 | 1967.7 | 1548.9 | 0.0 | 0.0 | 0.0 | 0.0 | 1777 | 43 |
| R106 | 1,741,654 | 1,451,439 | 17.4 | 14.5 | 1653.8 | 1439.3 | 0.0 | 0.0 | 0.0 | 0.0 | 1880 | 42 |
| R107 | 1,591,513 | 1,271,275 | 15.9 | 12.7 | 1512.6 | 1275.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1933 | 39 |
| R108 | 1,371,322 | 1,121,123 | 13.7 | 11.2 | 1321.6 | 1123.4 | 0.0 | 0.0 | 0.0 | 0.0 | 2008 | 37 |
| R109 | 1,761,610 | 1,411,373 | 17.6 | 14.1 | 1610.2 | 1372.9 | 0.0 | 0.0 | 0.0 | 0.0 | 1877 | 41 |
| R110 | 1,651,531 | 1,341,305 | 16.5 | 13.4 | 1531.1 | 1304.8 | 0.0 | 0.0 | 0.0 | 0.0 | 1915 | 40 |
| R111 | 1,661,564 | 1,291,258 | 16.6 | 12.9 | 1564.1 | 1258.3 | 0.0 | 0.0 | 0.0 | 0.0 | 1929 | 39 |
| R112 | 1,301,302 | 1,231,200 | 13.0 | 12.3 | 1302.3 | 1200.5 | 0.0 | 0.0 | 0.0 | 0.0 | 2163 | 42 |
| RC101 | 2,272,303 | 1,641,772 | 22.7 | 16.4 | 2303.3 | 1771.8 | 0.0 | 0.0 | 0.0 | 0.0 | 1872 | 46 |
| RC102 | 1,832,005 | 1,501,628 | 18.3 | 15.0 | 2005.2 | 1627.8 | 0.0 | 0.0 | 0.0 | 0.0 | 1920 | 44 |
| RC103 | 1,601,850 | 1,311,481 | 16.0 | 13.1 | 1849.9 | 1480.9 | 0.0 | 0.0 | 0.0 | 0.0 | 1965 | 41 |
| RC104 | 1,301,406 | 1,201,343 | 13.0 | 12.0 | 1406.1 | 1343.1 | 0.0 | 0.0 | 0.0 | 0.0 | 2100 | 41 |
| RC105 | 2,162,226 | 1,591,728 | 21.6 | 15.9 | 2225.6 | 1728.2 | 0.0 | 0.0 | 0.0 | 0.0 | 1837 | 44 |
| RC106 | 1,671,927 | 1,431,590 | 16.7 | 14.3 | 1927.1 | 1590.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1981 | 44 |
| RC107 | 1,521,586 | 1,301,466 | 15.2 | 13.0 | 1585.5 | 1465.7 | 0.0 | 0.0 | 0.0 | 0.0 | 2042 | 43 |
| RC108 | 1,461,554 | 1,221,363 | 14.6 | 12.2 | 1553.8 | 1363.2 | 0.0 | 0.0 | 0.0 | 0.0 | 2065 | 43 |
| morning_wave_120 | 557,430 | 270,973 | 19.1 | 15.7 | 890.3 | 702.9 | 0.0 | 0.0 | 0.0 | 0.0 | 3455 | 123 |

Wilcoxon signed-rank on plain_ga minus ga_alns per seed, Holm-adjusted across 21 instances within each metric (* below 0.05). Wins: ga_alns better / tied / worse, on cost.

| Instance | Cost wins | Cost p | Vans p | Distance p | Late p |
|---|---|---|---|---|---|
| R101 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R102 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R103 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R104 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R105 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R106 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R107 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R108 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R109 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R110 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R111 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| R112 | 9/0/1 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC101 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC102 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC103 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC104 | 9/0/1 | 0.0410 * | 0.0410 * | 0.0645 | 1.0000 |
| RC105 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC106 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC107 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| RC108 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |
| morning_wave_120 | 10/0/0 | 0.0410 * | 0.0410 * | 0.0410 * | 1.0000 |

Across the 21 instance means (plain_ga minus ga_alns). Cost and distance as a % of ga_alns's mean, vans and late crew in their own units. Above 0: ga_alns is better.

| Metric | Median difference | ga_alns better / tied / worse | p |
|---|---|---|---|
| cost | +22.49% | 21/0/0 | <0.0001 * |
| vehicles | +3.20 | 21/0/0 | <0.0001 * |
| distance | +17.78% | 21/0/0 | <0.0001 * |
| late_crew | +0.00 | 0/21/0 | 1.0000 |

**#71: uniform against adaptive (GA-ALNS).** The adaptive runs on morning_wave_120 are the GA-ALNS runs above.

| Instance | Cost uniform | Cost ga_alns | Vans uniform | Vans ga_alns | Distance uniform | Distance ga_alns | Late uniform | Late ga_alns | Unassigned uniform | Unassigned ga_alns | Generations uniform | Generations ga_alns |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| morning_wave_120 | 276,292 | 270,973 | 16.2 | 15.7 | 725.4 | 702.9 | 0.0 | 0.0 | 0.0 | 0.0 | 136 | 123 |
| smoke_30 | 73,771 | 73,738 | 5.0 | 5.0 | 226.2 | 226.3 | 0.0 | 0.0 | 0.0 | 0.0 | 361 | 339 |

Wilcoxon signed-rank on uniform minus ga_alns per seed, Holm-adjusted across 2 instances within each metric (* below 0.05). Wins: ga_alns better / tied / worse, on cost.

| Instance | Cost wins | Cost p | Vans p | Distance p | Late p |
|---|---|---|---|---|---|
| morning_wave_120 | 7/0/3 | 0.5508 | 0.2500 | 0.2617 | 1.0000 |
| smoke_30 | 1/9/0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

## Notes

Run 9 to 10 Nov 2026, 23:38 to 07:29 UTC (7 h 51 min), commit `fde9a70`, one run at a time on an otherwise idle laptop. Every run stopped at its time limit (at most 0.11 s over).

**Plain GA against GA-ALNS: GA-ALNS is better on every instance.**
- **Overall (21 instance means):** plain GA costs a median 22.5% more, uses 3.2 more vans and drives 17.8% further. GA-ALNS is better on all 21 instances for all three, p < 0.0001 (about 1e-6 for cost and distance). Leaving out R101 (below) changes nothing: 20 of 20, p about 2e-6.
- **Per instance:** GA-ALNS has the lower cost on every seed in 19 of 21 instances, and on 9 of 10 in R112 and RC104. Every cost and vans test is significant after Holm, and 20 of 21 distance tests: RC104's is not (0.0645; 9 of 10 seeds shorter).
- **Smallest and largest gaps:** R112, where plain GA costs 5.7% more, and morning_wave_120, where it costs 106% more (19.1 against 15.7 vans, 890 against 703 straight-line km).
- **Why so many p values are 0.0410:** with 10 seeds the smallest possible two-sided p is 2/1024 = 0.00195, and Holm across 21 instances multiplies it by 21. So 0.0410 is the floor, and Holm's step-down also lifts R112 and RC104 (9 of 10 seeds) to it. The per-instance tests cannot show more than that, and the overall test is where the strength of evidence is.

**The plain GA gets far more generations and still loses.**
- **Solomon:** 1,777 to 2,163 generations in 60 s against GA-ALNS's 37 to 47, 40 to 54 times as many (46 on average). A generation is 30 children.
- **morning_wave_120:** 3,455 against 123 in 120 s, 28 times as many.
- **So the gap isn't GA-ALNS getting more search.** A GA-ALNS child, with its destroy-and-repair, takes about as long as 46 plain-GA children, and it is worth far more.

**R101: the plain GA never found a feasible solution.**
- **All 10 plain-GA runs** used the whole 25-van fleet and still left 2 to 7 customers unassigned (5.2 on average). Solomon's check rejects them: these are the 10 rejected runs, and the unassigned penalty is why their cost is 52 billion.
- **Their distance leaves the unassigned customers out,** so it flatters the plain GA, which still drives further than GA-ALNS.
- **GA-ALNS solved R101 on every seed.** No other run lost, duplicated or left a pickup unassigned.

**Late crew is 0 for every run, so its tests carry no information.** A p of 1 here means nothing to test, not evidence of no difference. Where a method failed, it showed as unassigned customers (R101), not late ones.

**#71: adaptive selection makes no measurable difference.**
- **morning_wave_120:** adaptive's mean cost is 1.9% below uniform's, better on 7 of 10 seeds, with 15.7 against 16.2 vans and 3.1% less distance. None of it is significant: cost p 0.28 before Holm and 0.55 after, vans 0.25, distance 0.26.
- **smoke_30:** both find the same solution on 9 of 10 seeds. On the tenth uniform costs 324 more (0.4%).
- **Not for lack of updates:** a 120 s run makes about 3,700 mutations, so the weights update about 74 times (segments of 50).
- **What this means for the chapter:** GA-ALNS's gain over a plain GA comes from destroy-and-repair itself, not from adapting the operator weights. A 2% effect may be real but is smaller than the seed-to-seed spread; showing it would need many more seeds.

**Limits.**
- **Equal time, not equal evaluations,** as agreed. That is the comparison a dispatcher cares about, and the generation counts are shown so the difference in search effort is visible.
- **One machine,** so absolute generation counts depend on it; the ratios are what carry over.
- **morning_wave_120 uses haversine travel and straight-line km,** and its distance isn't in the crew fitness. Solomon distance comes from the independent `check_routes`.

Rebuild the tables with `python -m benchmarks.plain_ga --summary-only` from `backend/`; it keeps this section.
