# Solver design decisions

**Draft for #16.** This document covers why the GA-ALNS solver (`backend/app/solver/`) is built the way it is, what it leaves out and why, and what the evaluation shows about those choices. Each decision names the issue or PR where it was made and measured. The panel-feedback section has slots for the student to fill in from the proposal defence.

## 1. The problem

ACDOS plans one morning or evening wave of crew pickups. Each crew member is picked up somewhere in Nairobi and must reach JKIA before their rostered report time.

This is a capacitated VRP with time windows, many-to-one:
- many pickup origins and one destination;
- a hard deadline at the destination for each passenger;
- vans of 14 seats;
- one trip per van per wave.

Two consequences shape everything below:
- **The deadline is at JKIA, not at the stop.** A pickup has no time window of its own; what matters is when the van carrying that person reaches the airport. Fitness, Shaw relatedness and the construction heuristic all work from report times.
- **Travel time depends on departure time.** Nairobi's peaks lengthen the same journey by hour and day (the L2 multipliers), so the solver asks for a travel time *at a time of day*. That is what lets it use the Random Forest (§6).

## 2. Why a GA with ALNS as its mutation

**The design:** a steady-state genetic algorithm whose mutation step is one ALNS destroy-and-repair (`ga.py`, `mutation.py`). This is the hybrid from the proposal: GA recombination for exploring between solutions, and Ropke and Pisinger's (2006) large neighbourhood moves for improving within one.

| Piece | Choice | Where |
|---|---|---|
| Representation | Routes, one per van, plus an unassigned list. Also viewed as a giant tour, the routes end to end | `individual.py` (#7) |
| Initial population | 30 individuals: random giant tours through `split()`, plus the nearest-neighbour solution as a seed | `population.py` (#8), `nearest_neighbour.py` (#73) |
| Selection | Two binary tournaments | `ga.py` (#74) |
| Crossover | Order crossover (OX1) on giant tours, then `split()` back into routes, as in Prins (2004) | `crossover.py` (#9) |
| Mutation | One ALNS destroy (Shaw, random or worst) and one repair (greedy insertion), on every child | `mutation.py`, `removal.py`, `shaw.py`, `insertion.py` (#10, #11, #69) |
| Operator choice | Adaptive roulette weights (R&P), scores 33 / 9 / 13, segments of 50, reaction 0.1 | `mutation.py` (#71) |
| Replacement | Steady-state: the child replaces the worst individual if it is cheaper and not a duplicate | `ga.py` (#74) |
| Stopping | Time limit, a generation cap, or 30 generations without a new best | `ga.py` |

**Why steady-state:** it keeps elitism trivial. Only the worst individual is ever replaced, and only by a cheaper child, so the best cost never rises. It also gives the adaptive layer a clear meaning of "accepted": the child entered the population.

**Why `split()` is greedy, not Prins's optimal Split:** an optimal Split is a shortest path over the giant tour, but with time-dependent travel and deadlines at JKIA every arc's cost depends on when the van left. The greedy version fills vans in tour order and closes one when the next pickup would overfill it or make someone on it late. The ALNS step repairs the cuts it gets wrong.

**Lost causes:** a crew member who would be late even driven alone by any van must not use up a van of their own. They join the open route where they'd be least late (`late_even_alone`, `join_least_late_route`), and their lateness is reported, not hidden.

## 3. The fitness function

```
cost = U·1e10 + L·10,000 + K_late·18,000,000 + B·100 + R·100 + K·3,600 + (T + W)·1
```

| Term | Meaning |
|---|---|
| U | Unassigned crew |
| L | Lateness in seconds |
| K_late | Crew who are late (#75) |
| B | Shortfall against a 15-minute report buffer |
| R | Ride time over 90 minutes (#89) |
| K | Vans used |
| T | Driving time |
| W | Waiting at JKIA |

- **The weights are tiers.** Each higher term outweighs any realistic total of the terms below it. So the solver puts everyone in a van first, then gets them there on time, then keeps rides short, then saves vans and time.
- **K_late as well as L (#75):** with lateness alone, ten crew five minutes late cost the same as one crew member fifty minutes late. For a dispatcher, the number of people who miss report matters on its own.
- **Vans against time is a deliberate exchange rate,** not a tier. One van is worth an hour of driving and waiting. If saving a van always won, the solver would put crew reporting hours apart in one van and leave the early ones waiting at JKIA.
- **The ride term (#89):** waiting at JKIA is charged, but time in the van was free. So the GA built long zigzag routes that collected crew hours early and arrived just in time. The soft maximum ride time is from dial-a-ride (Cordeau and Laporte, 2003).
- **Latest-departure schedule:** each van leaves as late as it can and still meet its first deadline. W then measures the spread of report times on a route, not an early start (`individual.py`, at most 20 search steps).
- **A second profile for Solomon (#99):** `weights.SOLOMON` turns the buffer, ride and time terms off and charges distance. Its ranking is every window met, then fewest vehicles, then distance, which is how best-known solutions are ranked. The same solver code costs both kinds of problem.

## 4. Departures from Ropke and Pisinger (2006)

Each is in the code's docstrings and was measured where it changes results.

1. **Shaw relatedness uses report times** (deadlines at JKIA), not scheduled service times. It also drops the vehicle-compatibility term. Report times are fixed input, so the relatedness matrix is built once per problem. On Solomon it uses due times at the stop (`shaw.py`).
2. **Worst removal discounts unavoidable cost:** each pickup's saving is reduced by what it would cost even driven alone. Otherwise lost causes always look worst, and the operator would spend every call removing crew it can't help (`removal.py`).
3. **No noise in insertion costs.** R&P let the adaptive layer pick noisy or plain insertion. Here the GA population and crossover supply the diversity (`insertion.py`).
4. **"Accepted" means "entered the population",** not accepted by simulated annealing. There is no SA; steady-state replacement plays that role (`mutation.py`).

**Two speed-ups that keep the search the same or better (#85, #88, #109):**
- **Insertion fully costs only the 2 positions with the shortest detour in each route.** With fixed travel times, the others can't be cheaper on driving, lateness or waiting, and #88 measured 2 positions against 1 for the ride term.
- **Under RF travel it ranks detours at time 0,** an approximation that does change the plan. #109 kept it because it gives about 77 generations in 120 s against 34, and a cheaper plan on 4 of 4 clean seeds. At equal generations the two were level, so the gain is the extra search.

## 5. What was cut, and why

| Cut | Issue | Why | What the evidence says |
|---|---|---|---|
| Regret-2 insertion | #70 | Marked first to cut. Greedy is the only repair operator. | #71 found adaptive operator choice no better than uniform, so a second repair operator was unlikely to move the results. Regret-2 would insert first the crew whose only on-time van is about to fill. |
| Hyperparameter tuning | #14 | Kept the R&P values and those set during development. | GA-ALNS beat the plain GA on all 21 instances with them (#203). The 60 s distance gap is mostly time: 1.8 to 3.2% at 300 s (#211). Tuning on Solomon would fit a vans-first objective that isn't ACDOS's. |
| Removal cap with the stall limit | #94 | Part of #14. | A cap of q ≤ 20 broke the search under the ride term (#88), so removal stays at most 40% of routed crew. |
| Same-corridor Shaw term | #93 | Needed a with/without study under RF travel and a tuned weight. | Routes mix 3.1 corridors on average, a known limitation. The term would change the search, not the objective. |
| Multi-trip vans, vans starting where they are, crew on board a broken van | #135 | Re-planning keeps departed routes fixed (#113). | Listed as post-defence work. |

## 6. Travel time: haversine stand-in, then the Random Forest

- **The solver asks a function for travel time.** `Problem.travel_time(a, b, departure)` returns seconds, so the solver never knows which model it's using (`problem.py`).
- **Haversine at 30 km/h** was the stand-in while the RF was built, and is still what Solomon and `morning_wave_120` use.
- **Under the RF (#23),** the worker predicts the whole week once: every zone × weekday × hour, with `predict_grid`. `HourlyGrid` gives a time at any minute. A place is treated as its nearest of the 28 zones, and a zone matrix gives pickup-to-pickup legs (#102, #106).
- **Why in-process, not an HTTP call (#22):** travel time is asked for hundreds of thousands of times per run, and #109's profile found driving the routes is most of a run's time.

## 7. Re-planning after a disruption (#113)

- **Same POST as the first plan,** with a trigger: flight delay, standby activation or vehicle breakdown.
- **Departed routes are never re-planned,** except a broken-down van's in a breakdown re-plan.
- **A re-plan takes whole routes:** the routes of the requested pickups, and each requested van's undeparted route. So a van never has two active routes.
- **Messages never trigger re-optimisation (#54).** Only the dispatcher starts one.
- **The solve runs in a separate process (#51),** because pure Python holds the GIL for the whole time limit.

## 8. What the evaluation shows

| Question | Result | Where |
|---|---|---|
| Does destroy-and-repair beat a plain GA? | Yes, on all 21 instances, at equal time: median cost +22.5% for the plain GA, +3.2 vans, +17.8% distance (p < 0.0001). The plain GA ran 46× more generations and never found a feasible R101. | #203, `docs/results/203-plain-ga` |
| Does adaptive operator choice help? | Not measurably. On `morning_wave_120`, 1.9% lower cost, 7 of 10 seeds, p 0.55 after Holm. The gain comes from destroy-and-repair itself. | #71, #203 notes |
| How close to best-known on Solomon? | At 60 s, 4.4 to 12.5% over on distance for R101/R105/RC101/RC105. At 300 s, 1.8 to 3.2%. The van gap closes less: the best count is unchanged. | #13, #211 |
| Does planning with the RF matter? | Under RF travel, the RF plan has 100% of crew on time, against 25.2% for the haversine plan at its own departures and 93.0% re-timed (10 seeds, p 0.0039). It uses 18 to 20 vans against 15 to 17. | #210 |
| Is the RF good enough to plan with? | Held-out logger MAPE 7.00% after the #18/#19 features. | #19, #21 |

**Caveat for the defence:** #210's on-time rates are under the RF model, the same model the RF plan optimised against. They show the solver meets every deadline the model gives it, not an on-road on-time rate.

## 9. Panel feedback and how the design responds

From the proposal defence.

**What the panel said** [CHECK WORDING]: a pure GA is suboptimal for the CDVRPTW, because its random mutation rarely produces feasible, improving routes under tight time windows.

**What it recommended:** hybridise the GA with ALNS. Replace the mutation operator with Shaw (relatedness) removal and greedy re-insertion, following Ropke and Pisinger (2006), which is the state-of-the-art direction for VRPs with time windows.

**What changed:** the recommendation was adopted as section 2 describes. The GA keeps its population, representation (routes, also read as a giant tour) and crossover (OX1 with `split()`, as in Prins, 2004). So the Chapter 3 case for a population-based metaheuristic still holds, and only the mutation step changes, to destroy-and-repair:
- Shaw removal, plus random and worst removal as the other destroy operators;
- greedy re-insertion as the repair operator;
- adaptive roulette weights to choose between them.

**How the evidence answers it:**

| Question the feedback raises | Finding | Evidence |
|---|---|---|
| Does destroy-and-repair beat the GA's random mutation? | Yes. At equal time, GA-ALNS is better on all 21 instances (median cost +22.5% for the plain GA, p < 0.0001), despite running about 46× fewer generations. The plain GA never found a feasible R101: all 10 runs left pickups unassigned. | #203, `docs/results/203-plain-ga`, Figure 5.4 |
| Is the gain from the adaptive layer or from destroy-and-repair itself? | From destroy-and-repair. Adaptive operator choice against uniform choice: 1.9% lower cost, 7 of 10 seeds, p 0.55 after Holm, so not measurably different. | #71, `docs/results/71-operator-selection` |
| Is the hybrid competitive with published results? | Within 1.8 to 3.2% of best-known distance on R101, R105 and RC101 at 300 s, every run feasible on Solomon's checker. Van counts stay above best-known on R105, RC101 and RC105. | #13, #211, Figure 5.6 |

## References

- Cordeau, J.-F., & Laporte, G. (2003). A tabu search heuristic for the static multi-vehicle dial-a-ride problem. *Transportation Research Part B*, 37(6), 579–594.
- Davis, L. (1985). Applying adaptive algorithms to epistatic domains. *IJCAI*, 162–164.
- Prins, C. (2004). A simple and effective evolutionary algorithm for the vehicle routing problem. *Computers & Operations Research*, 31(12), 1985–2002.
- Ropke, S., & Pisinger, D. (2006). An adaptive large neighborhood search heuristic for the pickup and delivery problem with time windows. *Transportation Science*, 40(4), 455–472.
- Shaw, P. (1998). Using constraint programming and local search methods to solve vehicle routing problems. *CP-98*, 417–431.
- Solomon, M. M. (1987). Algorithms for the vehicle routing and scheduling problems with time window constraints. *Operations Research*, 35(2), 254–265.
